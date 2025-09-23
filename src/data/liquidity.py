from __future__ import annotations

import asyncio
import random
from typing import Tuple, Dict, Any

from ccxt.base.errors import DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, RequestTimeout

from .binance_client import normalize_symbol


_TRANSIENT = (DDoSProtection, RateLimitExceeded, ExchangeNotAvailable, RequestTimeout)


async def _fetch_order_book_safe(ex, sym: str, limit: int = 50) -> Dict[str, Any] | None:
    """
    Безопасный вызов стакана с экспоненциальным бэкоффом и джиттером.
    Возвращает None, если все попытки не удались.
    """
    delay = 0.5
    for attempt in range(5):
        try:
            return await ex.fetch_order_book(sym, limit=limit)
        except _TRANSIENT:
            # плавный бэкофф + небольшой джиттер
            await asyncio.sleep(delay + random.random() * 0.25)
            delay = min(8.0, delay * 2.0)
        except Exception:
            # не транзиентная ошибка — дальше не мучаем
            return None
    return None


async def _fetch_ticker_safe(ex, sym: str) -> Dict[str, Any] | None:
    """
    Фолбэк: быстрый тикер (best bid/ask) без глубины.
    """
    try:
        return await ex.fetch_ticker(sym)
    except _TRANSIENT:
        return None
    except Exception:
        return None


def _sum_depth_in_band(side, lower: float, upper: float) -> float:
    total = 0.0
    for px, qty in side:
        if lower <= px <= upper:
            total += float(px) * float(qty)  # считаем в нотионале USDT
    return total


async def check_liquidity_and_spread(
    ex,
    symbol: str,
    max_spread_bps: float,
    depth_bps: float,
    min_depth_usdt: float
) -> Tuple[bool, Dict[str, Any]]:
    """
    Устойчивая проверка:
      1) пытаемся стакан (limit=50) с ретраями;
      2) если стакан недоступен — фолбэк на тикер (spread считаем, depth = unknown);
      3) никогда не бросаем исключения наружу — только (ok, notes).
    """
    sym = normalize_symbol(symbol)

    # 1) Пытаемся получить стакан
    ob = await _fetch_order_book_safe(ex, sym, limit=50)

    if ob and (ob.get("bids") or ob.get("asks")):
        bids = ob.get("bids") or []
        asks = ob.get("asks") or []
        best_bid = float(bids[0][0]) if bids else None
        best_ask = float(asks[0][0]) if asks else None

        if not best_bid or not best_ask:
            # даже при наличии структуры стакана могло не быть котировок
            # попробуем фолбэк на тикер
            tk = await _fetch_ticker_safe(ex, sym)
            if tk and tk.get("bid") and tk.get("ask"):
                bid = float(tk["bid"]); ask = float(tk["ask"])
                mid = (bid + ask) / 2.0
                spread_bps = (ask - bid) / mid * 10000.0 if mid else 99999.0
                ok = bool((spread_bps <= max_spread_bps) and (min_depth_usdt <= 0.0))
                notes = {"reason": "fallback_ticker_only", "spread_bps": spread_bps, "mid": mid, "depth_checked": False}
                return ok, notes
            else:
                return False, {"reason": "no_bbo"}

        mid = (best_bid + best_ask) / 2.0
        spread_bps = (best_ask - best_bid) / mid * 10000.0 if mid else 99999.0

        # Диапазон цен для оценки нотионала в стакане
        lower = mid * (1 - float(depth_bps) / 10000.0)
        upper = mid * (1 + float(depth_bps) / 10000.0)

        depth_bid = _sum_depth_in_band(bids, lower, upper)
        depth_ask = _sum_depth_in_band(asks, lower, upper)

        ok = bool(
            (spread_bps <= float(max_spread_bps))
            and (depth_bid >= float(min_depth_usdt))
            and (depth_ask >= float(min_depth_usdt))
        )
        notes = {
            "spread_bps": spread_bps,
            "depth_bid": depth_bid,
            "depth_ask": depth_ask,
            "mid": mid,
            "depth_checked": True,
        }
        return ok, notes

    # 2) Стакана нет — пробуем быстрый тикер (хотя бы spread проверим)
    tk = await _fetch_ticker_safe(ex, sym)
    if tk and tk.get("bid") and tk.get("ask"):
        bid = float(tk["bid"]); ask = float(tk["ask"])
        mid = (bid + ask) / 2.0
        spread_bps = (ask - bid) / mid * 10000.0 if mid else 99999.0
        # без стакана глубину оценить не можем → ok только если она не требуется
        ok = bool((spread_bps <= max_spread_bps) and (min_depth_usdt <= 0.0))
        notes = {"reason": "fallback_ticker_only", "spread_bps": spread_bps, "mid": mid, "depth_checked": False}
        return ok, notes

    # 3) Совсем ничего не получилось
    return False, {"reason": "no_liquidity_data"}
