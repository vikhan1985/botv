from __future__ import annotations

def round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return (value // step) * step

def compute_position_qty(price: float, sl_pct: float, account_risk_usdt: float, step_size: float) -> float:
    '''
    qty = risk_usdt / (sl_pct * price)
    '''
    raw = account_risk_usdt / (sl_pct / 100.0 * price)
    # Use simple floor to step
    n = int(raw / step_size)
    return max(n * step_size, 0.0)
