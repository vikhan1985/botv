from __future__ import annotations
import pandas as pd

def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14):
    up = high.diff()
    down = -low.diff()
    plus_dm = (up.where((up > down) & (up > 0), 0.0))
    minus_dm = (down.where((down > up) & (down > 0), 0.0))

    tr1 = (high - low).abs()
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * (plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, 1e-9))
    minus_di = 100 * (minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, 1e-9))
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-9))
    adx_val = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx_val, plus_di, minus_di
