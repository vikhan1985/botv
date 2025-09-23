from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult
from ...indicators.atr import atr_wilder

class AtrFilter(Filter):
    name = "atr"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        df_sig = data["ohlcv_sig"]; df_htf = data["ohlcv_htf"]
        atr_sig = atr_wilder(df_sig["high"], df_sig["low"], df_sig["close"], 14)
        atr_htf = atr_wilder(df_htf["high"], df_htf["low"], df_htf["close"], 14)
        last_sig = float(df_sig["close"].iloc[-1]); last_htf = float(df_htf["close"].iloc[-1])
        atr_sig_pct = float(atr_sig.iloc[-1] / last_sig * 100.0)
        atr_htf_pct = float(atr_htf.iloc[-1] / last_htf * 100.0)
        ok = (atr_sig_pct >= cfg.ATR_15M_MIN_PCT) and (atr_htf_pct >= cfg.ATR_1H_MIN_PCT)
        # для уровней пригодится текущее ATR 1h:
        ctx["atr_sig_last"] = float(atr_sig.iloc[-1])
        return {
            "ok": bool(ok),
            "score": 1.0 if ok else 0.0,
            "notes": {"atr_sig_pct": atr_sig_pct, "atr_htf_pct": atr_htf_pct}
        }

from .base import register
register(AtrFilter)
