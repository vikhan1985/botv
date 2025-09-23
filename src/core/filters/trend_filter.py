from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult
from ...indicators.ema import ema
from ...indicators.rsi import rsi_wilder

class TrendFilter(Filter):
    name = "trend"
    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        df_sig = data["ohlcv_sig"]; df_htf = data["ohlcv_htf"]
        ema21 = ema(df_sig["close"], cfg.EMA_FAST)
        ema50 = ema(df_sig["close"], cfg.EMA_MID)
        ema200 = ema(df_sig["close"], cfg.EMA_SLOW)
        ema55h = ema(df_htf["close"], 55)
        last_sig = float(df_sig["close"].iloc[-1]); last_htf = float(df_htf["close"].iloc[-1])
        rsi = rsi_wilder(df_sig["close"], cfg.RSI_PERIOD)
        ltf_up = (ema21.iloc[-1] > ema50.iloc[-1]) and (last_sig > ema200.iloc[-1])
        ltf_dn = (ema21.iloc[-1] < ema50.iloc[-1]) and (last_sig < ema200.iloc[-1])
        htf_up = last_htf > ema55h.iloc[-1]; htf_dn = last_htf < ema55h.iloc[-1]
        rsi_long = rsi.iloc[-1] >= cfg.RSI_BUY_LVL; rsi_short = rsi.iloc[-1] <= cfg.RSI_SELL_LVL
        long = ltf_up and htf_up and rsi_long
        short = ltf_dn and htf_dn and rsi_short
        side = "long" if long else ("short" if short else "none")
        ctx["side_hint"] = side
        return {
            "ok": bool(long or short),
            "score": 1.0 if (long or short) else 0.0,
            "notes": {"rsi_sig": float(rsi.iloc[-1]), "side_hint": side}
        }

from .base import register
register(TrendFilter)
