from __future__ import annotations

import asyncio
import random
import time
import urllib.parse
import urllib.request
from typing import Any, Dict

from loguru import logger
from ccxt.base.errors import (
    DDoSProtection,
    RateLimitExceeded,
    ExchangeNotAvailable,
    RequestTimeout,
)

from .signals.detector_h15 import evaluate_symbol_h15
from .metrics.store import init_stats, log_signal_event  # NEW: stats

class Scheduler:
    def __init__(self, ex, router, settings, symbols, close_only: bool = False, scan_interval_ms: int = 120_000):
        self.ex = ex
        self.router = router
        self.s = settings
        self.symbols = symbols or []
        self.close_only = close_only
        self.scan_interval_ms = int(scan_interval_ms)
        self._sem = asyncio.Semaphore(int(getattr(self.s, "SCHED_MAX_PARALLEL", 6) or 6))

        # Stats init (safe)
        try:
            init_stats(self.s)
        except Exception as e:
            logger.warning("[STATS] init failed: %s", e)

        # Cooldown per symbol (seconds). Default 20 minutes (1200s).
        self.cooldown_sec: int = int(getattr(self.s, "SYMBOL_COOLDOWN_SEC", 20 * 60) or 0)
        self._last_signal_at: Dict[str, float] = {}

    # ---------------------------
    # Telegram helper (stdlib)
    # ---------------------------
    async def _notify_telegram(self, text: str) -> None:
        """Safe, non-blocking Telegram send via stdlib urllib in a thread pool."""
        s = self.s
        if not (
            getattr(s, "TELEGRAM_ENABLED", False)
            and getattr(s, "TELEGRAM_BOT_TOKEN", "")
            and getattr(s, "TELEGRAM_CHAT_ID", "")
        ):
            return

        url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": str(s.TELEGRAM_CHAT_ID),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")

        def _post():
            try:
                req = urllib.request.Request(url, data=data, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return resp.getcode(), body
            except Exception as e:
                return -1, str(e)

        loop = asyncio.get_running_loop()
        status, body = await loop.run_in_executor(None, _post)
        if status == 200:
            logger.info("[TG] sent OK")
        else:
            logger.error(f"[TG] send FAILED status={status} body={body}")

    # ---------------------------
    # Scheduler loop
    # ---------------------------
    async def run(self):
        logger.info(
            "[H15] scheduler started | interval_ms=%s parallel=%s",
            self.scan_interval_ms,
            self._sem._value,
        )
        while True:
            await self.scan_once()
            await asyncio.sleep(max(1.0, self.scan_interval_ms / 1000.0))

    async def scan_once(self):
        async def run_one(sym: str):
            async with self._sem:
                jitter_ms = int(getattr(self.s, "SCAN_JITTER_MS", 80) or 0)
                if jitter_ms > 0:
                    await asyncio.sleep(random.uniform(0, jitter_ms / 1000.0))
                await self._scan_symbol(sym)

        await asyncio.gather(*(run_one(sym) for sym in self.symbols))

    async def _scan_symbol(self, sym: str):
        # Получаем «пакет» по символу (фильтры, уровни, заметки)
        try:
            try:
                pack = await evaluate_symbol_h15(self.ex, sym, self.s)
            except TypeError:
                # если реализация синхронная
                pack = evaluate_symbol_h15(self.ex, sym, self.s)
        except (DDoSProtection, RateLimitExceeded) as e:
            logger.warning(f"[H15] {sym} [NET] rate limit: {e}; sleep 30s")
            await asyncio.sleep(30)
            return
        except (ExchangeNotAvailable, RequestTimeout) as e:
            logger.warning(f"[H15] {sym} [NET] transient: {e}; sleep 10s")
            await asyncio.sleep(10)
            return
        except Exception as e:
            logger.exception(f"[H15] {sym} scan error: {e}")
            return

        # Пакет None = отфильтровано на уровне стратегии (SRT/mandatory/near-SR и т.п.)
        if not pack:
            logger.debug(f"[H15] {sym} [SKIP] gated by SRT/MANDATORY/filters")
            return

        greens: Dict[str, Any] = pack.get("greens", {}) or {}
        passed = int(pack.get("passed", 0))
        needed = int(pack.get("needed", 9))

        logger.info(
            "[H15] {} [SIG] trend={} atr={} vwap={} oi={} ofi={} sr={} adx={} entry={} | passed={}/{}".format(
                sym,
                "Y" if greens.get("trend") else "N",
                "Y" if greens.get("atr") else "N",
                "Y" if greens.get("vwap") else "N",
                "Y" if greens.get("oi") else "N",
                "Y" if greens.get("ofi") else "N",
                "Y" if greens.get("sr") else "N",
                "Y" if greens.get("adx") else "N",
                "Y" if greens.get("entry") else "N",
                passed,
                needed,
            )
        )
        # Подсчёт mandatory-фильтров (читаем из top-level и, если пусто, из gates.*)
        _gates = getattr(self.s, 'gates', None)
        try:
            gates_dict = dict(_gates) if _gates else {}
        except Exception:
            gates_dict = _gates or {}
        mand_list = (getattr(self.s, 'MANDATORY_FILTERS', []) or gates_dict.get('MANDATORY_FILTERS', []) or [])
        mand_need = int(getattr(self.s, 'MANDATORY_REQUIRE_N', 0) or gates_dict.get('MANDATORY_REQUIRE_N', 0) or 0)
        mand_cnt = sum(1 for n in mand_list if greens.get(n, False) or (n == 'liquidity' and greens.get('liquidity')))

        rr1 = (pack.get('notes') or {}).get('rr1')
        try:
            _rr_min_dbg = rr_min  # if computed below
        except Exception:
            _rr_min_dbg = getattr(self.s, 'MIN_RR1', None)
        logger.info(
            f"[H15] {sym} [GATES] SRT={'Y' if greens.get('srt') else 'N'} | mandatory {mand_cnt}/{mand_need} | rr1={rr1} rr_min={_rr_min_dbg}"
        )

        await self._maybe_trigger(sym, pack, mand_cnt, mand_need)

    # ---------------------------
    # Trigger & fallback TG
    # ---------------------------
    async def _maybe_trigger(self, sym: str, pack: dict, mand_cnt: int, mand_need: int):
        """Проверка всех ворот и вызов роутера + fallback-уведомление в Telegram."""
        if not pack or pack.get("side") not in ("long", "short"):
            return

        # Cooldown (per symbol): если недавно отправляли по этой паре — пропускаем
        if self.cooldown_sec:
            now_ts = time.time()
            last_ts = self._last_signal_at.get(sym)
            if last_ts is not None and (now_ts - last_ts) < self.cooldown_sec:
                left = int(self.cooldown_sec - (now_ts - last_ts))
                logger.info("[SKIP] %s cooldown active: %ds left", sym, left)
                try:
                    log_signal_event(self.s, sym, pack, mand_cnt, mand_need, event="skipped", reason="cooldown")
                except Exception:
                    pass
                return

        greens = pack.get("greens", {}) or {}
        # SRT gate: учитываем флаг REQUIRE_SRT (top-level или gates.REQUIRE_SRT)
        _gates = getattr(self.s, 'gates', None)
        try:
            gates_dict = dict(_gates) if _gates else {}
        except Exception:
            gates_dict = _gates or {}
        _require_srt = bool(getattr(self.s, 'REQUIRE_SRT', False) or gates_dict.get('REQUIRE_SRT', False))
        srt_ok = bool(greens.get('srt')) if _require_srt else True
        entry_ok = bool(greens.get("entry", True))
        passed = int(pack.get("passed", 0))

        # mandatory gate
        mand_ok = (mand_cnt >= mand_need) if mand_need > 0 else True
        # RR gate (динамический порог)
        notes = pack.get('notes', {}) or {}
        rr1 = notes.get('rr1')
        if rr1 is None:
            # пересчёт на всякий случай
            entry = pack.get('entry')
            sl = pack.get('sl')
            tp1 = pack.get('tp1')
            if entry not in (None, 0) and sl not in (None, entry) and tp1 is not None:
                rr1 = abs((tp1 - entry) / (entry - sl))
            else:
                rr1 = 0.0
        base_rr_min = float(getattr(self.s, 'MIN_RR1', 1.0))
        rr_min_floor = float(getattr(self.s, 'RR_MIN_FLOOR', 1.0))
        adapt = bool(getattr(self.s, 'RR_ADAPT_BY_STRENGTH', False))
        strong = int(getattr(self.s, 'MIN_PASSED', 8))
        bonus = float(getattr(self.s, 'RR_STRONG_BONUS', 0.0))
        very_delta = int(getattr(self.s, 'RR_VERY_STRONG_DELTA', 1))
        rr_min = base_rr_min
        if adapt:
            if passed >= strong:
                rr_min -= bonus
            if passed >= strong + very_delta:
                rr_min -= bonus
            if rr_min < rr_min_floor:
                rr_min = rr_min_floor
        rr_ok = rr1 >= rr_min

        # Минимум прошедших фильтров (защита от «сырых» сетапов)
        if passed < 6:
            try:
                log_signal_event(self.s, sym, pack, mand_cnt, mand_need, event="skipped", reason="passed<6")
            except Exception:
                pass
            return

        # Если требуется подтверждение на закрытии — сообщаем, но не блокируем роутер (поведение как было)
        if getattr(self.s, "REQUIRE_CONFIRM_ON_CLOSE", False):
            logger.info(f"[H15] {sym} [CONFIRM_ON_CLOSE] pending bar close for side={pack.get('side')}")

        # Решение: сигнал валиден?
        is_valid_signal = bool(srt_ok and mand_ok and rr_ok and entry_ok)

        # 1) Страхующий пуш в Telegram (если сигнал валиден) — независим от роутера
        if is_valid_signal:
            # Резервируем кулдаун сразу, чтобы исключить дубль до отправки
            self._last_signal_at[sym] = time.time()

            try:
                log_signal_event(self.s, sym, pack, mand_cnt, mand_need, event="sent", reason="ok")
            except Exception:
                pass

            side = pack.get("side")
            entry = pack.get("entry"); sl = pack.get("sl"); tp1 = pack.get("tp1"); tp2 = pack.get("tp2")

            
            def _fmt(x):
                try:
                    return f"{float(x):.6g}"
                except Exception:
                    return str(x)

            # ---- Telegram message (human-friendly, RU) ----
            def _yn(k: str) -> str:
                return "✅" if bool(greens.get(k)) else "❌"

            side_txt = (side or "").upper()
            side_emoji = "🚀" if side_txt == "LONG" else "🔻"

            # ensure rr1 is available
            rr1_val = rr1 if isinstance(rr1, (int, float)) else 0.0
            try:
                rr1_val = float(rr1)
            except Exception:
                # try compute from entry/sl/tp1
                try:
                    if entry not in (None, 0) and sl not in (None, entry) and tp1 is not None:
                        rr1_val = abs((tp1 - entry) / (entry - sl))
                except Exception:
                    rr1_val = 0.0

            needed_total = int(pack.get('needed', 9))

            text = (
                f"{sym} | {side_txt} {side_emoji}\n"
                f"Entry: {_fmt(entry)} ｜ SL: {_fmt(sl)} ｜ TP1: {_fmt(tp1)} ｜ TP2: {_fmt(tp2)}\n"
                f"RR1: {rr1_val:.2f} ｜ passed {passed}/{needed_total}\n\n"
                f"Основные:\n"
                f"OFI {_yn('ofi')} · VWAP {_yn('vwap')} · OI {_yn('oi')}\n\n"
                f"Контекст:\n"
                f"SRT {_yn('srt')} · SR {_yn('sr')} · ADX {_yn('adx')} · TREND {_yn('trend')}\n\n"
                f"Технические:\n"
                f"LIQUIDITY {_yn('liquidity')} · ATR {_yn('atr')} · ENTRY {_yn('entry')} · CANDLE {_yn('candle')}"
            )
            logger.info(
                "[ALERT] sending TG for %s side=%s rr1=%.2f (mandatory %s/%s)",
                sym, side, rr1, mand_cnt, mand_need
            )
            try:
                await self._notify_telegram(text)
            except Exception as e:
                logger.error(f"[TG] fallback alert error: {e}")
        else:
            # log skip with reason
            reason = "gate"
            if not srt_ok:
                reason = "srt"
            elif not mand_ok:
                reason = "mandatory"
            elif not rr_ok:
                reason = "rr"
            elif not entry_ok:
                reason = "entry"
            try:
                log_signal_event(self.s, sym, pack, mand_cnt, mand_need, event="skipped", reason=reason)
            except Exception:
                pass

        # 2) Вызов роутера (как и раньше)
        handler = getattr(self.router, "on_signal", None)
        if callable(handler):
            try:
                await handler(self.ex, sym, pack, close_only=self.close_only)
            except Exception as e:
                logger.warning(f"[H15] {sym} router.on_signal error: {e}")
