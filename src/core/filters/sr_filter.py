from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult

def _range_breakout(df, lookback: int, side_hint: str, confirm_bps: int = 0) -> tuple[bool, float, float, float]:
    if df is None or df.empty or lookback <= 1:
        return False, 0.0, 0.0, 0.0
    hi = float(df["high"].tail(lookback).max())
    lo = float(df["low"].tail(lookback).min())
    c = float(df["close"].iloc[-1])
    buf = (confirm_bps or 0) / 10000.0
    if side_hint == "long":
        return (c > hi * (1.0 + buf)), hi, lo, c
    elif side_hint == "short":
        return (c < lo * (1.0 - buf)), hi, lo, c
    return False, hi, lo, c

class SrFilter(Filter):
    name = "sr"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        df = data["ohlcv_sig"]; side = ctx.get("side_hint", "none")
        look = max(4, min(12, getattr(cfg, "SWING_LOOKBACK_H15", 6)))
        ok, hi, lo, c = _range_breakout(df, look, side, int(getattr(cfg, "SR_CONFIRM_BPS", 0)))
        # только breakout; near-SR и fallback делаем наверху (знает про другие фильтры)
        # посчитаем «недоход» к уровню в bps, пригодится для near-SR/fallback
        if side == "long":
            dist = max(0.0, hi - c); base = hi or 1.0
        elif side == "short":
            dist = max(0.0, c - lo); base = lo or 1.0
        else:
            dist, base = 0.0, 1.0
        dist_bps = (dist / base) * 10000.0
        return {"ok": bool(ok), "score": 1.0 if ok else 0.0, "notes": {"hi": hi, "lo": lo, "dist_bps": dist_bps}}

from .base import register
register(SrFilter)
