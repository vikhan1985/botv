from __future__ import annotations

import pandas as pd
from typing import Tuple

async def daily_vwap(ex, symbol: str) -> Tuple[float, dict]:
    '''
    Compute day VWAP since 00:00 UTC using 1m if available (fallback 5m).
    vwap = sum(price * volume) / sum(volume), where price = typical (H+L+C)/3.
    '''
    # try 1m up to current day bars
    try:
        df = pd.DataFrame(await ex.fetch_ohlcv(symbol, timeframe="1m", limit=1440),
                          columns=["ts","o","h","l","c","v"])
    except Exception:
        df = pd.DataFrame(await ex.fetch_ohlcv(symbol, timeframe="5m", limit=288),
                          columns=["ts","o","h","l","c","v"])
    if df.empty:
        return 0.0, {"reason": "no_ohlcv"}
    # keep only today's UTC
    from datetime import datetime, timezone
    start_utc = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_ts = int(start_utc.timestamp() * 1000)
    df = df[df["ts"] >= start_ts]
    tp = (df["h"] + df["l"] + df["c"]) / 3.0
    pv = tp * df["v"]
    v = df["v"].replace(0, 1e-9)
    vwap = (pv.sum() / v.sum()) if v.sum() > 0 else float(df["c"].iloc[-1])
    notes = {"bars": len(df)}
    return float(vwap), notes
