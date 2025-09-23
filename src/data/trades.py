from __future__ import annotations

async def compute_ofi_cvd(ex, symbol: str, window_sec: int = 300) -> tuple[float, float, dict]:
    '''
    Compute OFI and CVD on last `window_sec` seconds using recent trades.
    OFI = (buy - sell) / (buy + sell), in USDT notionals.
    CVD = cumulative (buy - sell) USDT over window.
    '''
    trades = await ex.fetch_trades(symbol, limit=1000)
    now_ms = ex.milliseconds()
    cutoff = now_ms - window_sec * 1000
    buy, sell = 0.0, 0.0
    for t in trades:
        ts = t.get('timestamp')
        if ts is None or ts < cutoff:
            continue
        price = float(t['price'])
        amount = float(t['amount'])
        side_is_sell_maker = t.get('info', {}).get('m')
        notional = price * amount
        if side_is_sell_maker:
            sell += notional
        else:
            buy += notional
    denom = buy + sell
    ofi = (buy - sell) / denom if denom > 0 else 0.0
    cvd = (buy - sell)
    notes = {"buy_usdt": buy, "sell_usdt": sell, "count": len(trades)}
    return ofi, cvd, notes
