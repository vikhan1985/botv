from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

@dataclass
class OrderResult:
    id: str
    price: float
    amount: float
    side: str
    type: str
    status: str
    reduce_only: bool = False

class DryRunner:
    def __init__(self, ex) -> None:
        self.ex = ex
        self.positions: Dict[str, Dict[str, float]] = {}
        self.orders: Dict[str, OrderResult] = {}

    async def create_order(self, symbol: str, type_: str, side: str, amount: float, price: float | None, params: dict) -> OrderResult:
        ticker = await self.ex.fetch_ticker(symbol)
        px = price or ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
        order = OrderResult(id=f"dry-{len(self.orders)+1}", price=float(px), amount=float(amount), side=side, type=type_, status="closed", reduce_only=params.get("reduceOnly", False))
        self.orders[order.id] = order
        pos = self.positions.setdefault(symbol, {"qty": 0.0, "entry": 0.0})
        if not order.reduce_only:
            if side == "buy":
                new_qty = pos["qty"] + order.amount
            else:
                new_qty = pos["qty"] - order.amount
            pos["entry"] = order.price
            pos["qty"] = new_qty
        else:
            if side == "sell":
                pos["qty"] = max(0.0, pos["qty"] - order.amount)
            else:
                pos["qty"] = min(0.0, pos["qty"] + order.amount)
        return order

class RealRouter:
    def __init__(self, ex) -> None:
        self.ex = ex

    async def create_order(self, symbol: str, type_: str, side: str, amount: float, price: float | None, params: dict):
        return await self.ex.create_order(symbol, type_, side, amount, price, params)
