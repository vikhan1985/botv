
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from loguru import logger

from ..config import load_settings
from ..metrics.store import init_stats, summarize, format_report

def main():
    p = argparse.ArgumentParser("stats")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--period", choices=["day","month"], default="day")
    p.add_argument("--date", help="YYYY-MM-DD (for period=day)")
    p.add_argument("--month", help="YYYY-MM (for period=month)")
    p.add_argument("--send-tg", action="store_true", help="also send to Telegram")
    args = p.parse_args()

    s = load_settings(args.config)
    init_stats(s)

    if args.period == "day":
        key = args.date or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        key = args.month or datetime.now(tz=timezone.utc).strftime("%Y-%m")

    summary = summarize(args.period, key)
    text = format_report(summary)
    print(text)

    if args.send_tg and getattr(s, "TELEGRAM_ENABLED", False):
        # Minimal sender (avoid Scheduler import)
        import urllib.parse, urllib.request
        url = f"https://api.telegram.org/bot{s.TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": str(s.TELEGRAM_CHAT_ID),
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }
        data = urllib.parse.urlencode(payload).encode("utf-8")
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, method="POST"), timeout=10) as resp:
                if resp.getcode() == 200:
                    logger.info("[STATS] report sent to Telegram")
                else:
                    logger.warning("[STATS] TG response %s", resp.getcode())
        except Exception as e:
            logger.warning("[STATS] send TG failed: %s", e)

if __name__ == "__main__":
    main()
