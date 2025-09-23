from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult

class OiFilter(Filter):
    name = "oi"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        side = ctx.get("side_hint", "none")
        val = data.get("oi_change_pct", None)
        if val is None or side == "none":
            return {"ok": False, "score": 0.0, "notes": {"oi_delta_pct": val}}
        if side == "long":
            ok = float(val) >= cfg.OI_MIN_CHANGE_PCT_15M
        else:
            ok = float(val) <= -cfg.OI_MIN_CHANGE_PCT_15M
        return {"ok": bool(ok), "score": 1.0 if ok else 0.0, "notes": {"oi_delta_pct": float(val)}}

from .base import register
register(OiFilter)
