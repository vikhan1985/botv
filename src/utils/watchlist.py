from __future__ import annotations

from typing import List, Tuple
from loguru import logger
from ..data.liquidity import check_liquidity_and_spread
from ..data.klines import fetch_ohlcv_df
from ..indicators.atr import atr_wilder
from ..config import Settings

async def build_watchlist(ex, s: Settings, top: int = 15) -> list[str]:
    '''
    Собирает USDT-M swap пары, которые проходят:
      - спред/глубину (liquidity)
      - волатильность ATR(14,15m)/Price ≥ s.ATR_15M_MIN_PCT
    Ранжирует по 24h quoteVolume и возвращает топ-N (символы в формате ccxt, например 'BTC/USDT:USDT').
    '''
    await ex.load_markets()
    markets = [
        m for m in ex.markets.values()
        if m.get("type") == "swap" and m.get("quote") == "USDT" and m.get("settle") == "USDT" and m.get("active", True)
    ]

    candidates: List[Tuple[float, float, str]] = []
    for m in markets:
        sym = m["symbol"]
        try:
            liq_ok, _ = await check_liquidity_and_spread(
                ex, sym, s.MAX_SPREAD_BPS, s.DEPTH_BPS, s.MIN_DEPTH_USDT
            )
            if not liq_ok:
                continue

            df15 = await fetch_ohlcv_df(ex, sym, s.BASE_TIMEFRAME, limit=200)
            if df15.empty:
                continue
            atr15 = float(atr_wilder(df15["high"], df15["low"], df15["close"], 14).iloc[-1])
            last = float(df15["close"].iloc[-1])
            atr15_pct = atr15 / last * 100.0
            if atr15_pct < s.ATR_15M_MIN_PCT:
                continue

            t = await ex.fetch_ticker(sym)
            qv = float(t.get("quoteVolume") or t.get("info", {}).get("quoteVolume") or 0.0)

            candidates.append((qv, atr15_pct, sym))
        except Exception as e:
            logger.debug(f"[H15] watchlist skip {sym}: {e}")
            continue

    candidates.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top_syms = [sym for _, __, sym in candidates[:top]]
    logger.info(f"[H15] [WATCHLIST] picked {len(top_syms)} symbols: {top_syms}")
    return top_syms
