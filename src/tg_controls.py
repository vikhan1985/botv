
from __future__ import annotations

import os, asyncio, json, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from loguru import logger

from .config import load_settings
from .metrics.store import init_stats, summarize, format_report

API = "https://api.telegram.org/bot{token}/{method}"

def _load_env_file(env_path: str = ".env") -> None:
    p = Path(env_path)
    if not p.exists():
        return
    try:
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip(); v = v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        logger.warning("[ENV] failed to parse .env: %s", e)

def _post(token: str, method: str, data: dict) -> tuple[int, str]:
    url = API.format(token=token, method=method)
    body = urllib.parse.urlencode(data).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return -1, str(e)

def _get(token: str, method: str, params: dict) -> tuple[int, str]:
    qs = urllib.parse.urlencode(params)
    url = API.format(token=token, method=method) + ("?" + qs if qs else "")
    try:
        with urllib.request.urlopen(url, timeout=50) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return -1, str(e)

def _kb_stats(today_label="📊 Сегодня", yest_label="📄 Вчера", month_label="🗓 Текущий месяц"):
    return {"inline_keyboard": [
        [{"text": today_label, "callback_data": "stats:day:today"},
         {"text": yest_label, "callback_data": "stats:day:yesterday"}],
        [{"text": month_label, "callback_data": "stats:month:this"}],
    ]}

def _now_local(tzname: str):
    tz = ZoneInfo(tzname) if ZoneInfo else timezone.utc
    return datetime.now(tz=tz)

def _resolve_key(kind: str, tzname: str):
    now = _now_local(tzname)
    if kind == "day:today":
        return now.strftime("%Y-%m-%d")
    if kind == "day:yesterday":
        return (now - timedelta(days=1)).strftime("%Y-%m-%d")
    if kind == "month:this":
        return now.strftime("%Y-%m")
    return None

async def main(config_path: str = "config.yaml"):
    # 0) Load .env (if present) into os.environ
    _load_env_file(".env")

    s = load_settings(config_path)
    init_stats(s)

    # Prefer environment variables, fallback to settings
    token = os.getenv("TELEGRAM_BOT_TOKEN") or getattr(s, "TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or str(getattr(s, "TELEGRAM_CHAT_ID", "") or "")
    tzname = os.getenv("STATS_TZ") or getattr(s, "STATS_TZ", "UTC")
    offset_file = os.getenv("STATS_OFFSET_FILE") or getattr(s, "STATS_OFFSET_FILE", "data/tg_offset.txt")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN/CHAT_ID not configured (env or config)")
        return

    # If webhook was set earlier, disable it to enable getUpdates
    _post(token, "deleteWebhook", {"drop_pending_updates": "true"})

    Path(offset_file).parent.mkdir(parents=True, exist_ok=True)
    offset = 0
    if Path(offset_file).exists():
        try:
            offset = int(Path(offset_file).read_text().strip() or "0")
        except Exception:
            offset = 0

    logger.info("[TG CTRL] started. Listening for /stats and buttons…")
    logger.info("[TG CTRL] expecting chat_id=%s (from env/config)", chat_id)

    while True:
        params = {"timeout": 45, "offset": offset + 1}
        status, body = _get(token, "getUpdates", params)
        if status != 200:
            logger.warning("[TG CTRL] getUpdates failed: %s %s", status, body); await asyncio.sleep(2); continue
        try:
            data = json.loads(body); updates = data.get("result", [])
        except Exception as e:
            logger.warning("[TG CTRL] bad response: %s", e); await asyncio.sleep(2); continue

        if not updates:
            continue

        for upd in updates:
            upd_id = upd.get("update_id", 0)
            offset = max(offset, upd_id)
            Path(offset_file).write_text(str(offset))

            # Buttons
            cb = upd.get("callback_query")
            if cb:
                msg = cb.get("message") or {}
                from_chat = msg.get("chat", {}).get("id")
                cbid = cb.get("id")
                payload = (cb.get("data") or "")
                if from_chat and (not chat_id or str(from_chat) == chat_id) and payload.startswith("stats:"):
                    _, scope, which = payload.split(":", 2)  # stats:day:today
                    key = _resolve_key(f"{scope}:{which}", tzname)
                    if key:
                        summary = summarize(scope, key)
                        text = format_report(summary)
                        _post(token, "answerCallbackQuery", {"callback_query_id": cbid})
                        _post(token, "sendMessage", {"chat_id": from_chat, "text": text, "parse_mode": "HTML",
                                                     "reply_markup": json.dumps(_kb_stats())})
                continue

            # Text
            msg = upd.get("message")
            if not msg:
                continue
            from_chat = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()

            # If chat_id in config is empty, auto-bind to the first chat
            if not chat_id:
                chat_id = str(from_chat)
                logger.info("[TG CTRL] auto-bound to chat_id=%s", chat_id)

            if str(from_chat) != chat_id:
                # ignore other chats
                continue

            if not text:
                continue

            if text.startswith("/start") or text.startswith("/menu"):
                _post(token, "sendMessage", {"chat_id": from_chat, "text": "Выберите отчёт:",
                                             "reply_markup": json.dumps(_kb_stats())})
                continue

            if text.startswith("/stats"):
                parts = text.split()
                if len(parts) == 1:
                    key = _resolve_key("day:today", tzname); summary = summarize("day", key)
                    txt = format_report(summary)
                    _post(token, "sendMessage", {"chat_id": from_chat, "text": txt, "parse_mode": "HTML",
                                                 "reply_markup": json.dumps(_kb_stats())}); continue
                elif len(parts) == 2:
                    arg = parts[1]
                    if len(arg) == 10: summary = summarize("day", arg)
                    elif len(arg) == 7: summary = summarize("month", arg)
                    else:
                        _post(token, "sendMessage", {"chat_id": from_chat, "text": "Формат: /stats YYYY-MM-DD или YYYY-MM"}); continue
                    txt = format_report(summary)
                    _post(token, "sendMessage", {"chat_id": from_chat, "text": txt, "parse_mode": "HTML",
                                                 "reply_markup": json.dumps(_kb_stats())}); continue
                else:
                    _post(token, "sendMessage", {"chat_id": from_chat, "text": "Формат: /stats [YYYY-MM-DD|YYYY-MM]"}); continue
