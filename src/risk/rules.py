from __future__ import annotations
from loguru import logger

class RiskState:
    def __init__(self, daily_max_loss_usdt: float, cooldown_min: int, max_positions: int) -> None:
        self.daily_pnl = 0.0
        self.daily_max_loss = daily_max_loss_usdt
        self.close_only = False
        self.cooldown_min = cooldown_min
        self.max_positions = max_positions
        self.last_entry_ts_by_symbol: dict[str, float] = {}
        self.open_positions = 0

    def record_pnl(self, delta: float) -> None:
        self.daily_pnl += delta
        if self.daily_pnl <= -abs(self.daily_max_loss):
            logger.warning("[H15] [RISK] DailyPnL=%.2f USDT → close-only", self.daily_pnl)
            self.close_only = True

    def can_enter(self, symbol: str, now_ts: float) -> bool:
        if self.close_only:
            return False
        if self.open_positions >= self.max_positions:
            return False
        last = self.last_entry_ts_by_symbol.get(symbol, 0.0)
        cool = self.cooldown_min * 60.0
        return (now_ts - last) >= cool

    def mark_enter(self, symbol: str, now_ts: float) -> None:
        self.last_entry_ts_by_symbol[symbol] = now_ts
        self.open_positions += 1

    def mark_exit(self, symbol: str) -> None:
        self.open_positions = max(0, self.open_positions - 1)
