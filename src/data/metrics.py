from __future__ import annotations

from collections import deque
import time
from typing import Dict, Deque, Tuple
from .binance_client import normalize_symbol

_OI_RING: Dict[str, Deque[Tuple[int, float]]] = {}

async def fetch_open_interest(ex, symbol: str) -> float:
    sym = normalize_symbol(symbol)
    try:
        oi = await ex.fetch_open_interest(sym)
        if isinstance(oi, dict):
            return float(oi.get("openInterestAmount") or oi.get("openInterest") or 0.0)
        return float(oi)
    except Exception:
        return 0.0

async def update_oi_ring(ex, symbol: str) -> None:
    now_ms = ex.milliseconds()
    oi = await fetch_open_interest(ex, symbol)
    ring = _OI_RING.setdefault(symbol, deque(maxlen=1000))
    ring.append((now_ms, oi))

def _find_oi_point(ring: Deque[Tuple[int, float]], ms_ago_min: int, ms_ago_max: int, now_ms: int) -> float | None:
    target_min = now_ms - ms_ago_max
    target_max = now_ms - ms_ago_min
    candidates = [v for ts, v in ring if target_min <= ts <= target_max]
    if not candidates:
        return None
    return candidates[0]

def compute_delta_oi_pct(symbol: str, ex_now_ms: int) -> float:
    ring = _OI_RING.get(symbol)
    if not ring:
        return 0.0
    now_ms = ex_now_ms
    current = ring[-1][1]
    ref = _find_oi_point(ring, ms_ago_min=15*60*1000, ms_ago_max=30*60*1000, now_ms=now_ms)
    if ref is None or ref == 0:
        return 0.0
    return (current - ref) / ref * 100.0


async def get_oi_change_pct(ex, symbol: str, window_min: int = 30) -> float:
    """Return Open Interest % change over ~window_min minutes, using exchange clock."""
    sym = normalize_symbol(symbol)
    # refresh OI ring
    await update_oi_ring(ex, sym)
    now_ms = ex.milliseconds() if hasattr(ex, "milliseconds") else int(time.time() * 1000)
    return compute_delta_oi_pct(sym, now_ms)
