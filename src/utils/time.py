from __future__ import annotations

from datetime import datetime, timezone
import pytz

def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)

def now_tz(tz_name: str) -> datetime:
    return datetime.now(tz=pytz.timezone(tz_name))

def utc_ms() -> int:
    return int(now_utc().timestamp() * 1000)
