from __future__ import annotations
from typing import Dict, Any
from ..config import Settings
from ..core.provider_ccxt import CCXTProvider
from ..core.strategy_h15 import evaluate_strategy_h15

async def evaluate_symbol_h15(ex, symbol: str, s: Settings) -> Dict[str, Any] | None:
    """
    Обёртка: грузим DataSlice через провайдер и прогоняем через плагинную стратегию.
    Сигнатура сохранена под текущий планировщик/роутер.
    """
    provider = CCXTProvider(ex)
    data = await provider.load(symbol, s)

    # Если нет данных по 1h/4h — ранний выход (совместимо со старым поведением)
    if (data.get("ohlcv_sig") is None or data["ohlcv_sig"].empty) or (data.get("ohlcv_htf") is None or data["ohlcv_htf"].empty):
        return {
            "symbol": symbol, "side": "none",
            "greens": {"liquidity": bool(data.get("liq_ok", False))},
            "passed": int(bool(data.get("liq_ok", False))), "needed": 9,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "notes": {"reason": "no_ohlcv", **(data.get("liq_notes") or {})}
        }

    return await evaluate_strategy_h15(symbol, data, s)
