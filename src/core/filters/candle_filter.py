from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult

class CandleFilter(Filter):
    name = "candle"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        df = data.get("ohlcv_sig")
        side = ctx.get("side_hint", "none")
        if df is None or df.empty or side == "none":
            return {"ok": False, "score": 0.0, "notes": {"reason": "no_data_or_side"}}

        try:
            o = float(df["open"].iloc[-1]); h = float(df["high"].iloc[-1])
            l = float(df["low"].iloc[-1]);  c = float(df["close"].iloc[-1])
        except Exception:
            return {"ok": False, "score": 0.0, "notes": {"reason": "bad_ohlcv"}}

        rng = max(1e-12, h - l)
        upper = h - max(o, c)
        lower = min(o, c) - l
        upper_pct = 100.0 * upper / rng
        lower_pct = 100.0 * lower / rng
        expansion_bps = (rng / max(1e-12, c)) * 10_000.0

        max_up = getattr(cfg, "MAX_UPPER_WICK_PCT", None)
        max_lo = getattr(cfg, "MAX_LOWER_WICK_PCT", None)
        max_exp = getattr(cfg, "MAX_BAR_EXPANSION_BPS", None)

        ok = True
        if max_exp is not None:
            ok = ok and (expansion_bps <= float(max_exp))
        if side == "long" and max_up is not None:
            ok = ok and (upper_pct <= float(max_up))
        if side == "short" and max_lo is not None:
            ok = ok and (lower_pct <= float(max_lo))

        return {"ok": bool(ok), "score": 1.0 if ok else 0.0,
                "notes": {"upper_wick_pct": upper_pct, "lower_wick_pct": lower_pct, "expansion_bps": expansion_bps}}

from .base import register
register(CandleFilter)
