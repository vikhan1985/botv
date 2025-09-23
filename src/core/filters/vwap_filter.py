from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult

class VwapFilter(Filter):
    name = "vwap"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        vwap_val = data.get("vwap", None)
        if vwap_val is None:
            return {"ok": False, "score": 0.0, "notes": {"vwap": None}}
        df_sig = data["ohlcv_sig"]
        side = ctx.get("side_hint", "none")
        # 2 последних часа в сторону VWAP
        last_closes = df_sig["close"].tail(2)
        dev_bps = ((float(last_closes.iloc[-1]) / float(vwap_val)) - 1.0) * 10_000.0
        dev_min = getattr(cfg, "VWAP_DEV_BPS_MIN", None)
        if side == "long":
            ok = bool((last_closes > vwap_val).all()) and (True if dev_min is None else (dev_bps >= float(dev_min)))
        elif side == "short":
            ok = bool((last_closes < vwap_val).all()) and (True if dev_min is None else ((-dev_bps) >= float(dev_min)))
        else:
            ok = False
        return {"ok": ok, "score": 1.0 if ok else 0.0, "notes": {"vwap": float(vwap_val)}}

from .base import register
register(VwapFilter)
