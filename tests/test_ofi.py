import types
import asyncio
import random

class DummyEx:
    def milliseconds(self): 
        return 1_700_000_000_000
    async def fetch_trades(self, symbol, limit=1000):
        out = []
        ts = self.milliseconds() - 200_000
        for i in range(100):
            ts += 1000
            px = 100 + random.random()
            amt = 0.1
            m = (i % 2 == 0)
            out.append({"timestamp": ts, "price": px, "amount": amt, "info": {"m": m}})
        return out

from src.data.trades import compute_ofi_cvd

def test_ofi_runs():
    ex = DummyEx()
    ofi, cvd, notes = asyncio.get_event_loop().run_until_complete(compute_ofi_cvd(ex, "BTC/USDT:USDT", 300))
    assert -1.0 <= ofi <= 1.0
