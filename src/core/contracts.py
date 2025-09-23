from __future__ import annotations
from typing import Protocol, TypedDict, Any
import pandas as pd

class DataSlice(TypedDict, total=False):
    # Таймфреймы
    ohlcv_sig: pd.DataFrame   # 1h
    ohlcv_htf: pd.DataFrame   # 4h
    ohlcv_5m:  pd.DataFrame | None
    ohlcv_15m: pd.DataFrame | None

    # Предрассчитанные метрики
    vwap: float | None
    oi_change_pct: float | None
    ofi: float | None
    cvd: float | None

    # Ликвидность/спред
    liq_ok: bool
    liq_notes: dict[str, Any]

class FilterResult(TypedDict, total=False):
    ok: bool
    score: float
    notes: dict[str, Any]

class Filter(Protocol):
    name: str
    async def run(self, symbol: str, data: DataSlice, cfg: "Settings", ctx: dict[str, Any]) -> FilterResult: ...

class Strategy(Protocol):
    async def evaluate(self, symbol: str, data: DataSlice, cfg: "Settings") -> dict[str, Any]: ...
