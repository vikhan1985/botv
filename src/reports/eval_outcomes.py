
from __future__ import annotations

import argparse
from typing import List, Tuple
from loguru import logger

from ..config import load_settings
from ..metrics.store import init_stats, update_outcome, _connect

# Optional: only symbol normalizer (no async exchange import)
try:
    from ..data.binance_client import normalize_symbol
except Exception:
    normalize_symbol = None

import ccxt

def _get_exchange_sync():
    ex = ccxt.binance()
    try:
        ex.load_markets()
    except Exception as e:
        logger.warning("load_markets failed: %s", e)
    return ex

def _fetch_ohlcv(ex, symbol: str, tf: str, since_ms: int, limit: int = 1500):
    try:
        return ex.fetch_ohlcv(symbol, timeframe=tf, since=since_ms, limit=limit)
    except Exception as e:
        if normalize_symbol is not None:
            try:
                sym2 = normalize_symbol(symbol)
                return ex.fetch_ohlcv(sym2, timeframe=tf, since=since_ms, limit=limit)
            except Exception:
                pass
        raise

def _decide_outcome(side: str, sl: float, tp1: float, tp2: float | None,
                    ohlc: List[Tuple[int,float,float,float,float,float]], tie: str):
    """
    Return (outcome, closed_ts, tp1_ts, tp2_ts, sl_ts) or (None, None, None, None, None) if still open.
    tie: 'worst'|'best' — if SL and TP are touched within same candle
    """
    outcome = None
    closed_ts = tp1_ts = tp2_ts = sl_ts = None

    for ts, o, h, l, c, v in ohlc:
        if side == "long":
            hit_sl = (l <= sl)
            hit_tp2 = (h >= (tp2 if tp2 is not None else float('inf')))
            hit_tp1 = (h >= tp1)
            if hit_sl and (hit_tp1 or hit_tp2):
                if tie == "worst":
                    outcome = "SL"; sl_ts = ts
                else:
                    if hit_tp2: outcome = "TP2"; tp2_ts = ts
                    else: outcome = "TP1"; tp1_ts = ts
                closed_ts = ts
                break
            if hit_tp2:
                outcome = "TP2"; tp2_ts = ts; closed_ts = ts; break
            if hit_tp1:
                outcome = "TP1"; tp1_ts = ts; closed_ts = ts; break
            if hit_sl:
                outcome = "SL";  sl_ts = ts;  closed_ts = ts; break
        else:  # short
            hit_sl = (h >= sl)
            hit_tp2 = (l <= (tp2 if tp2 is not None else -float('inf')))
            hit_tp1 = (l <= tp1)
            if hit_sl and (hit_tp1 or hit_tp2):
                if tie == "worst":
                    outcome = "SL"; sl_ts = ts
                else:
                    if hit_tp2: outcome = "TP2"; tp2_ts = ts
                    else: outcome = "TP1"; tp1_ts = ts
                closed_ts = ts
                break
            if hit_tp2:
                outcome = "TP2"; tp2_ts = ts; closed_ts = ts; break
            if hit_tp1:
                outcome = "TP1"; tp1_ts = ts; closed_ts = ts; break
            if hit_sl:
                outcome = "SL";  sl_ts = ts;  closed_ts = ts; break

    return outcome, closed_ts, tp1_ts, tp2_ts, sl_ts

def _load_open_signals(period_filter=None):
    # period_filter optionally restricts by date (YYYY-MM-DD) or month (YYYY-MM)
    with _connect() as conn:
        cur = conn.cursor()
        if period_filter and len(period_filter) == 10:
            cur.execute("SELECT id, symbol, side, entry, sl, tp1, tp2, ts FROM signals WHERE sent=1 AND closed=0 AND date=?", (period_filter,))
        elif period_filter and len(period_filter) == 7:
            cur.execute("SELECT id, symbol, side, entry, sl, tp1, tp2, ts FROM signals WHERE sent=1 AND closed=0 AND substr(date,1,7)=?", (period_filter,))
        else:
            cur.execute("SELECT id, symbol, side, entry, sl, tp1, tp2, ts FROM signals WHERE sent=1 AND closed=0")
        return cur.fetchall()

def main():
    ap = argparse.ArgumentParser("eval_outcomes")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--tf", default="1m", help="evaluation timeframe (default 1m)")
    ap.add_argument("--tie", choices=["worst","best"], default="worst", help="if SL and TP hit same bar")
    ap.add_argument("--date", help="YYYY-MM-DD to eval only that date")
    ap.add_argument("--month", help="YYYY-MM to eval only that month")
    args = ap.parse_args()

    s = load_settings(args.config)
    init_stats(s)
    ex = _get_exchange_sync()

    period = args.date or args.month
    rows = _load_open_signals(period_filter=period)
    if not rows:
        logger.info("[EVAL] no open signals to evaluate")
        return

    for row in rows:
        row_id, symbol, side, entry, sl, tp1, tp2, ts = row
        if not (symbol and side and sl and tp1):
            continue
        since_ms = int((ts - 60) * 1000)  # start slightly before
        try:
            ohlc = _fetch_ohlcv(ex, symbol, args.tf, since_ms, limit=1500)
        except Exception as e:
            logger.warning("[EVAL] fetch_ohlcv failed for %s: %s", symbol, e)
            continue
        outcome, closed_ts, tp1_ts, tp2_ts, sl_ts = _decide_outcome(side, float(sl), float(tp1), float(tp2) if tp2 is not None else None, ohlc, args.tie)
        if outcome:
            # convert ms to s for DB
            update_outcome(row_id, outcome, int(closed_ts/1000), int(tp1_ts/1000) if tp1_ts else None, int(tp2_ts/1000) if tp2_ts else None, int(sl_ts/1000) if sl_ts else None)
            logger.info("[EVAL] %s id=%s outcome=%s", symbol, row_id, outcome)

if __name__ == "__main__":
    main()
