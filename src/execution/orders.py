from __future__ import annotations

from ..data.binance_client import normalize_symbol

async def _place_entry(router, symbol: str, side: str, amount: float, price: float | None, post_only: bool = True):
    sym = normalize_symbol(symbol)
    px = None if price is None else float(router.ex.price_to_precision(sym, price))
    amt = float(router.ex.amount_to_precision(sym, amount))
    params = {"postOnly": True} if post_only else {}
    order = await router.create_order(sym, "limit" if price else "market", side, amt, px, params)
    return order


async def _place_reduce_limit(router, symbol: str, side: str, amount: float, price: float):
    sym = normalize_symbol(symbol)
    px = float(router.ex.price_to_precision(sym, price))
    amt = float(router.ex.amount_to_precision(sym, amount))
    params = {"reduceOnly": True, "postOnly": True}
    return await router.create_order(sym, "limit", side, amt, px, params)


async def _place_reduce_sl(router, symbol: str, side: str, amount: float, stop_price: float):
    sym = normalize_symbol(symbol)
    spx = float(router.ex.price_to_precision(sym, stop_price))
    amt = float(router.ex.amount_to_precision(sym, amount))
    params = {"reduceOnly": True, "stopPrice": spx}
    return await router.create_order(sym, "stop_market", side, amt, None, params)


async def enter_with_targets(router, symbol: str, side: str, qty: float, entry: float, tp1: float, tp2: float, sl: float):
    # entry
    await _place_entry(router, symbol, side, qty, entry, post_only=True)
    # targets
    half = qty / 2.0
    exit_side = "sell" if side == "buy" else "buy"
    await _place_reduce_limit(router, symbol, exit_side, half, tp1)
    await _place_reduce_limit(router, symbol, exit_side, qty - half, tp2)
    # stop
    await _place_reduce_sl(router, symbol, exit_side, qty, sl)
