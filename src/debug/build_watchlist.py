# src/debug/build_watchlist.py
from __future__ import annotations
import asyncio
from loguru import logger

from ..config import load_settings
from ..utils.logging import setup_logging
from ..data.binance_client import get_exchange
from ..data.liquidity import check_liquidity_and_spread
from ..data.klines import fetch_ohlcv_df
from ..indicators.atr import atr_wilder

async def build(limit: int = 15):
    setup_logging("INFO")
    s = load_settings("config.yaml")
    ex = get_exchange(s.BINANCE_API_KEY, s.BINANCE_API_SECRET, s.TESTNET)
    await ex.load_markets()

    markets = [
        m for m in ex.markets.values()
        if m.get("type") == "swap" and m.get("quote") == "USDT" and m.get("settle") == "USDT" and m.get("active", True)
    ]

    scored = []
    for m in markets:
        sym = m["symbol"]
        try:
            # 1) ликвидность/спред
            liq_ok, _notes = await check_liquidity_and_spread(
                ex, sym, s.MAX_SPREAD_BPS, s.DEPTH_BPS, s.MIN_DEPTH_USDT
            )
            if not liq_ok:
                continue

            # 2) волатильность (ATR 15m)
            df15 = await fetch_ohlcv_df(ex, sym, s.BASE_TIMEFRAME, limit=200)
            if df15.empty:
                continue
            atr15 = float(atr_wilder(df15["high"], df15["low"], df15["close"], 14).iloc[-1])
            last = float(df15["close"].iloc[-1])
            atr15_pct = atr15 / last * 100.0
            if atr15_pct < s.ATR_15M_MIN_PCT:
                continue

            # 3) 24h объём (quoteVolume)
            t = await ex.fetch_ticker(sym)
            qv = float(t.get("quoteVolume") or t.get("info", {}).get("quoteVolume") or 0.0)

            scored.append((qv, atr15_pct, sym))
        except Exception:
            continue

    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    top = [s for _, __, s in scored[:limit]]
    print("Рекомендованный watchlist:")
    print(",".join([sym.replace("/USDT:USDT", "USDT").replace("/", "") for sym in top]))

    await ex.close()

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    a = ap.parse_args()
    asyncio.run(build(a.limit))

if __name__ == "__main__":
    main()
