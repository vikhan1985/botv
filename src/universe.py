import asyncio
from typing import List, Dict, Any, Optional, Tuple

async def _load_markets(ex):
    try:
        return await ex.load_markets()
    except Exception:
        return {}

async def _fetch_tickers(ex):
    try:
        return await ex.fetch_tickers()
    except Exception:
        return None

async def _fetch_ticker(ex, sym: str):
    try:
        return await ex.fetch_ticker(sym)
    except Exception:
        return None

async def _fetch_ohlcv(ex, sym: str, tf='1h', limit=200):
    try:
        return await ex.fetch_ohlcv(sym, timeframe=tf, limit=limit)
    except Exception:
        return None

def _quote_volume_24h(t):
    if not t: return None
    for k in ('quoteVolume','quoteVolume24h','quoteVolume24hQuote'):
        v = t.get(k)
        if v is not None:
            try: return float(v)
            except Exception: pass
    info = t.get('info') if isinstance(t.get('info'), dict) else {}
    for k in ('quoteVolume','quote_volume','turnover','turnoverUsd'):
        v = info.get(k)
        if v is not None:
            try: return float(v)
            except Exception: pass
    base_vol = t.get('baseVolume'); last = t.get('last') or t.get('close')
    try:
        if base_vol is not None and last: return float(base_vol)*float(last)
    except Exception: pass
    return None

def _spread_bps(t) -> float:
    bid, ask = t.get('bid'), t.get('ask')
    try:
        if bid and ask and bid>0 and ask>0:
            mid = (bid+ask)/2.0
            return (ask-bid)/mid*10_000.0
    except Exception: pass
    return 9999.0

def _atr_percent(ohlcv, period=14):
    if not ohlcv or len(ohlcv)<period+1: return None
    trs=[]; prev=ohlcv[0][4]
    for _,o,h,l,c,_ in ohlcv[1:]:
        tr=max(h-l, abs(h-prev), abs(l-prev)); trs.append(tr); prev=c
    if len(trs)<period: return None
    atr=sum(trs[-period:])/period; px=ohlcv[-1][4] or 0
    if px<=0: return None
    return (atr/px)*100.0

def _adx(ohlcv, period=14):
    if not ohlcv or len(ohlcv)<period+1: return None
    trs=[]; plus_dm=[]; minus_dm=[]
    for i in range(1,len(ohlcv)):
        _,o1,h1,l1,c1,_=ohlcv[i-1]; _,o2,h2,l2,c2,_=ohlcv[i]
        up=h2-h1; dn=l1-l2
        plus_dm.append(up if (up>dn and up>0) else 0.0)
        minus_dm.append(dn if (dn>up and dn>0) else 0.0)
        trs.append(max(h2-l2, abs(h2-c1), abs(l2-c1)))
    if len(trs)<period: return None
    atr=sum(trs[-period:])/period
    if atr==0: return None
    pdi=(sum(plus_dm[-period:])/period)/atr*100.0
    mdi=(sum(minus_dm[-period:])/period)/atr*100.0
    denom=(pdi+mdi) or 1e-9
    return abs(pdi-mdi)/denom*100.0

def _pick_candidates(markets: Dict[str, Any]) -> List[str]:
    contracts, spots = [], []
    for sym,m in markets.items():
        if not m.get('active',True): continue
        if m.get('quote')!='USDT': continue
        if m.get('contract') or m.get('swap') or m.get('future'):
            if m.get('linear') is False: continue
            contracts.append(sym)
        elif m.get('spot'):
            spots.append(sym)
    return contracts if len(contracts)>=30 else (contracts + [s for s in spots if s not in contracts])

async def build_classic_watchlist(ex, settings, top_n:int=60) -> List[str]:
    markets = await _load_markets(ex)
    if not markets: return ['BTC/USDT','ETH/USDT','SOL/USDT'][:top_n]
    candidates = _pick_candidates(markets)
    if not candidates: return ['BTC/USDT','ETH/USDT','SOL/USDT'][:top_n]
    tickers = await _fetch_tickers(ex)

    liq_min = float(getattr(settings,'LIQ_MIN_USDT_24H',20_000_000))
    max_spread = float(getattr(settings,'MAX_SPREAD_BPS',7.0))

    prelim = []
    for sym in candidates:
        t = tickers.get(sym) if isinstance(tickers,dict) else None
        if t is None:
            t = await _fetch_ticker(ex, sym)
            if t is None: continue
        qv = _quote_volume_24h(t); sp=_spread_bps(t)
        if qv is None or qv<liq_min: continue
        if sp>max_spread: continue
        prelim.append((sym,qv,sp))

    if not prelim:
        pool=[]
        if isinstance(tickers,dict):
            for sym,t in tickers.items():
                if '/USDT' not in sym and 'USDT' not in sym: continue
                qv=_quote_volume_24h(t)
                if qv: pool.append((sym,qv))
        if not pool: return ['BTC/USDT','ETH/USDT','SOL/USDT'][:top_n]
        pool.sort(key=lambda x:x[1], reverse=True)
        prelim=[(s,v,0.0) for s,v in pool[:max(top_n*2,60)]]

    sem = asyncio.Semaphore(int(getattr(settings,'SCHED_MAX_PARALLEL',6) or 6))
    async def enrich(sym:str):
        async with sem:
            ohlcv = await _fetch_ohlcv(ex, sym, tf='1h', limit=200)
        return sym, _atr_percent(ohlcv), _adx(ohlcv)

    tasks=[enrich(s) for s,_,_ in prelim]; enriched=[]
    for i in range(0,len(tasks),24):
        enriched += await asyncio.gather(*tasks[i:i+24])

    atr_min = float(getattr(settings,'ATR_1H_MIN_PCT',0.6))
    adx_min = float(getattr(settings,'ADX_H1_MIN',24))
    merged=[]; vol_map={s:v for s,v,_ in prelim}
    for sym,atrp,adx in enriched:
        if atrp is None or adx is None: continue
        if atrp<atr_min or adx<adx_min: continue
        merged.append((sym,vol_map.get(sym,0.0),atrp,adx))

    if not merged:
        prelim.sort(key=lambda x:x[1], reverse=True)
        return [s for s,_,_ in prelim[:top_n]]

    def _rank(vals, reverse=True):
        idx=sorted(range(len(vals)), key=lambda i: vals[i], reverse=reverse)
        r=[0]*len(vals); 
        for pos,i in enumerate(idx): r[i]=len(vals)-pos
        return r
    vols=[v for _,v,_,_ in merged]; atrs=[a for *_,a,_ in merged]; adxs=[d for *_ ,d in merged]
    rv,ra,rd=_rank(vols,True),_rank(atrs,True),_rank(adxs,True)
    scored=[(0.5*rv[i]+0.3*ra[i]+0.2*rd[i], sym) for i, (sym,_,_,_) in enumerate(merged)]
    scored.sort(reverse=True)
    return [sym for _,sym in scored[:top_n]]
