# -*- coding: utf-8 -*-
# src/data/binance_client.py

from __future__ import annotations

from typing import Optional
import ccxt.async_support as ccxt


def _clean(s: Optional[str]) -> str:
    """Очищает строку от пробелов и кавычек, если переменная отсутствует — возвращает пустую строку."""
    return (s or "").strip().strip('"').strip("'")


async def get_exchange(s):
    """
    Создаёт async-клиент ccxt.binanceusdm.
    - Ключи добавляются ТОЛЬКО если реально заданы (позволяет работать без ключей).
    - Включает sandbox при TESTNET=true.
    - Включён внутренний rate-limit ccxt, чтобы снижать риск 418.
    """
    api = _clean(getattr(s, "BINANCE_API_KEY", ""))
    sec = _clean(getattr(s, "BINANCE_API_SECRET", ""))

    cfg = {
        "enableRateLimit": True,   # внутренний троттлинг ccxt
        "rateLimit": 300,          # ~3 req/сек
        "timeout": 20000,
        "options": {
            "defaultType": "future",
            "adjustForTimeDifference": True,
        },
    }
    # креды добавляем только если оба заданы
    if api and sec:
        cfg["apiKey"] = api
        cfg["secret"] = sec

    ex = ccxt.binanceusdm(cfg)

    # testnet (фьючерсы USDT-M)
    if bool(getattr(s, "TESTNET", False)):
        try:
            ex.set_sandbox_mode(True)
        except Exception:
            pass

    return ex


def normalize_symbol(symbol: str) -> str:
    """
    Унифицирует символ к формату фьючерсов USDT-M, понятному ccxt/binanceusdm.

    Примеры:
      "BTCUSDT"        -> "BTC/USDT:USDT"
      "BTC/USDT"       -> "BTC/USDT:USDT"
      "BTC/USDT:USDT"  -> "BTC/USDT:USDT" (без изменений)
    """
    if not symbol:
        return symbol
    sym = symbol.strip().upper()

    # уже нормализован
    if "/USDT:USDT" in sym:
        return sym

    # спотовый формат -> фьючерсный
    if sym.endswith("/USDT"):
        return sym.replace("/USDT", "/USDT:USDT")

    # короткий формат BTCUSDT -> BTC/USDT:USDT
    if sym.endswith("USDT") and "/" not in sym:
        base = sym[:-4]
        return f"{base}/USDT:USDT"

    return sym
