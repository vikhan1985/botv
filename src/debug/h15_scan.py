from __future__ import annotations

import argparse
import asyncio
from loguru import logger
from ..config import load_settings
from ..utils.logging import setup_logging
from ..data.binance_client import get_exchange
from ..signals.detector_h15 import evaluate_symbol_h15

async def run_once(symbols: list[str], loglevel: str, testnet: bool):
    setup_logging(loglevel)
    s = load_settings("config.yaml")
    if testnet:
        s.TESTNET = True
    ex = get_exchange(s.BINANCE_API_KEY, s.BINANCE_API_SECRET, testnet=s.TESTNET)
    await ex.load_markets()
    for sym in symbols:
        pack = await evaluate_symbol_h15(ex, sym, s)
        side = pack["side"]
        greens = pack["greens"]
        passed = pack["passed"]
        entry = pack["entry"]
        sl = pack["sl"]
        tp1 = pack["tp1"]
        tp2 = pack["tp2"]
        greens_list = [k for k,v in greens.items() if v]
        logger.info(f"[H15] {sym}: side={side} passed={passed}/8 greens={greens_list} entry={entry} sl={sl} tp1={tp1} tp2={tp2}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT")
    ap.add_argument("--loglevel", type=str, default="INFO")
    ap.add_argument("--testnet", action="store_true")
    a = ap.parse_args()
    symbols = [s.strip() for s in a.symbols.split(",") if s.strip()]
    asyncio.run(run_once(symbols, a.loglevel, a.testnet))

if __name__ == "__main__":
    main()
