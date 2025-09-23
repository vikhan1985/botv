from __future__ import annotations
from typing import Any
import numpy as np
from .contracts import DataSlice
from ..data.binance_client import normalize_symbol
from ..data.klines import fetch_ohlcv_df
from ..data.liquidity import check_liquidity_and_spread

async def _calc_daily_vwap_from_5m(ex, symbol: str) -> float | None:
    try:
        df5 = await fetch_ohlcv_df(ex, symbol, "5m", limit=400)
        if df5 is None or df5.empty:
            return None
        last_ts = int(df5["ts"].iloc[-1])
        day_ms = 24 * 60 * 60 * 1000
        utc_midnight = last_ts - (last_ts % day_ms)
        df_day = df5[df5["ts"] >= utc_midnight]
        if df_day.empty:
            df_day = df5.tail(12)
        tp = (df_day["high"] + df_day["low"] + df_day["close"]) / 3.0
        pv = tp * df_day["vol"]
        v = df_day["vol"].replace(0, np.nan)
        return float((pv.sum() / v.sum()))
    except Exception:
        return None

class CCXTProvider:
    """Провайдер данных из ccxt-обёрток проекта (HTTP)."""
    def __init__(self, ex) -> None:
        self.ex = ex

    async def load(self, symbol: str, cfg) -> DataSlice:
        sym = normalize_symbol(symbol)

        # OHLCV
        df_sig = await fetch_ohlcv_df(self.ex, sym, cfg.BASE_TIMEFRAME, limit=500)   # 1h
        df_htf = await fetch_ohlcv_df(self.ex, sym, cfg.TREND_TF_SLOW, limit=500)    # 4h
        df_5m  = await fetch_ohlcv_df(self.ex, sym, "5m",  limit=300)
        df_15m = await fetch_ohlcv_df(self.ex, sym, "15m", limit=300)

        # VWAP
        vwap = await _calc_daily_vwap_from_5m(self.ex, sym)

        # Ликвидность/спред
        liq_ok, liq_notes = await check_liquidity_and_spread(self.ex, sym, cfg.MAX_SPREAD_BPS, cfg.DEPTH_BPS, cfg.MIN_DEPTH_USDT)

        # ΔOI
        oi_change = None
        try:
            from ..data.metrics import get_oi_change_pct  # type: ignore
            oi_change = float(await get_oi_change_pct(self.ex, sym, window_min=30))
        except Exception:
            pass

        # OFI/CVD
        ofi_val, cvd_val = None, None
        try:
            from ..data.trades import compute_ofi_cvd
            ofi_val, cvd_val, _ = await compute_ofi_cvd(self.ex, sym, int(cfg.OFI_WINDOW_SEC))
        except Exception:
            pass

        return DataSlice(
            ohlcv_sig=df_sig, ohlcv_htf=df_htf, ohlcv_5m=df_5m, ohlcv_15m=df_15m,
            vwap=vwap, oi_change_pct=oi_change, ofi=ofi_val, cvd=cvd_val,
            liq_ok=bool(liq_ok), liq_notes=liq_notes or {}
        )
