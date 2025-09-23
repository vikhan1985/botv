from __future__ import annotations

import pandas as pd
from ccxt.base.errors import BadSymbol
from .binance_client import normalize_symbol

COLUMNS = ["ts", "open", "high", "low", "close", "vol"]

# Base-asset aliases for rebrands ( extend if needed )
ALIASES_BASE = {
    "MATIC": "POL",   # Binance USDⓈ-M uses POL now
}

async def _resolve_symbol_for_ccxt(ex, sym: str) -> str:
    """
    Map any incoming 'sym' to a real market key present in ex.markets for binanceusdm.
    We prefer linear SWAP/USDT contracts.
    """
    raw = (sym or "").upper().replace(":USDT", "")
    base = raw
    if "/USDT" in raw:
        base = raw.split("/USDT")[0]
    elif raw.endswith("USDT"):
        base = raw[:-4]
    base = base.replace("/", "")

    # apply known rebrand aliases
    base = ALIASES_BASE.get(base, base)

    # Ensure markets are loaded
    try:
        if not getattr(ex, "markets", None):
            await ex.load_markets()
    except Exception:
        # continue anyway; fallbacks below
        pass

    markets = getattr(ex, "markets", {}) or {}

    # 1) Direct scan through markets for the correct contract
    for m in markets.values():
        try:
            if not m.get("contract", False):
                continue
            if m.get("quote", "").upper() != "USDT":
                continue
            if m.get("base", "").upper() != base:
                continue
            # Prefer linear swap
            if m.get("linear", True) is False:
                continue
            return m.get("symbol") or m.get("info", {}).get("symbol") or m.get("id")
        except Exception:
            continue

    # 2) Common candidates
    candidates = [
        f"{base}/USDT:USDT",
        f"{base}/USDT",
        f"{base}USDT",
    ]
    for c in candidates:
        if c in markets:
            return c

    # 3) Fallback: let ccxt build a safe symbol (local)
    try:
        sc = ex.safe_symbol(f"{base}/USDT", marketType="swap")
        if sc in markets:
            return sc
    except Exception:
        pass

    # Last resort: return original; caller will try and handle
    return sym


async def fetch_ohlcv_df(ex, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
    """
    Robust OHLCV fetch with USDⓈ-M symbol resolution.
    Returns an empty DataFrame on failure (never raises), preserving columns COLUMNS.
    """
    log = None
    try:
        import logging
        log = logging.getLogger(__name__)
    except Exception:
        pass

    # Start from normalized form used by the project
    sym0 = normalize_symbol(symbol)

    # Resolve to an actual market key first
    sym_candidates = []

    # Primary resolved
    sym_resolved = await _resolve_symbol_for_ccxt(ex, sym0)
    sym_candidates.append(sym_resolved)

    # If normalized produced something exotic, also try RAW
    if sym_resolved != symbol:
        sym_resolved_raw = await _resolve_symbol_for_ccxt(ex, symbol)
        if sym_resolved_raw not in sym_candidates:
            sym_candidates.append(sym_resolved_raw)

    # Add generic candidates for extra safety
    raw_u = (symbol or "").upper().replace(":USDT", "")
    base = raw_u
    if "/USDT" in raw_u:
        base = raw_u.split("/USDT")[0]
    elif raw_u.endswith("USDT"):
        base = raw_u[:-4]
    base = base.replace("/", "")
    base = ALIASES_BASE.get(base, base)

    extra = [f"{base}/USDT", f"{base}/USDT:USDT", f"{base}USDT"]
    for c in extra:
        if c not in sym_candidates:
            sym_candidates.append(c)

    # Try candidates sequentially
    for sc in sym_candidates:
        try:
            ohlcv = await ex.fetch_ohlcv(sc, timeframe=timeframe, limit=limit)
            if ohlcv:
                df = pd.DataFrame(ohlcv, columns=COLUMNS)
                return df
        except BadSymbol as e:
            if log: log.debug(f"[KLN] BadSymbol for {symbol} -> {sc}: {e}")
            continue
        except Exception as e:
            # transient error; try next, but log
            if log: log.debug(f"[KLN] fetch_ohlcv error for {symbol} -> {sc}: {e}")
            continue

    # If nothing worked — return empty DF (so верхний слой не падает)
    if log: log.warning(f"[KLN] all candidates failed for {symbol}: {sym_candidates}")
    return pd.DataFrame(columns=COLUMNS)
