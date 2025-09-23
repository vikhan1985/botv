import asyncio, sqlite3, time
from typing import List, Dict, Any, Optional

def _cfg(settings, key, default):
    try: return getattr(settings, key)
    except Exception: return default

def _now_ms(): return int(time.time()*1000)

def _exp_decay_weight(ts_ms: int, half_life_hours: float = 72.0) -> float:
    age_h = max(0.0, (_now_ms() - int(ts_ms or 0)) / 3600000.0)
    return 0.5 ** (age_h / half_life_hours) if half_life_hours>0 else 1.0

def _open_stats(path: str):
    try:
        conn = sqlite3.connect(path); conn.row_factory = sqlite3.Row; return conn
    except Exception: return None

def _list_tables(conn): 
    try: return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    except Exception: return []

def _detect_columns(conn, table: str):
    cur = conn.execute(f"PRAGMA table_info({table})"); 
    return {row[1]: row[0] for row in cur.fetchall()}

def _fetch_rows(conn, days: int = 14):
    tables = _list_tables(conn)
    candidates = [t for t in tables if any(k in t.lower() for k in ("signals","events","candidates","stats"))] or tables
    rows=[]; cutoff=_now_ms()-days*24*3600*1000
    for tbl in candidates:
        cols=_detect_columns(conn, tbl)
        sym_col = next((c for c in cols if c.lower() in ("symbol","sym","pair")), None)
        ts_col  = next((c for c in cols if c.lower() in ("ts","timestamp","time_ms","created_at_ms")), None)
        passed_col = next((c for c in cols if c.lower() in ("passed","passed_filters","passed_count")), None)
        event_col  = next((c for c in cols if c.lower() in ("event","type","action","status")), None)
        rr_col     = next((c for c in cols if c.lower() in ("rr","rr1","rr_min")), None)
        if not sym_col or not ts_col: continue
        q=f"SELECT {sym_col} as symbol, {ts_col} as ts"
        if passed_col: q+=", "+passed_col+" as passed"
        if event_col:  q+=", "+event_col+" as event"
        if rr_col:     q+=", "+rr_col+" as rr1"
        q += f" FROM {tbl} WHERE {ts_col} >= ?"
        try:
            cur=conn.execute(q,(cutoff,))
            rows+=cur.fetchall()
        except Exception: 
            continue
    return rows

def _score(rows, min_passed_needed: int) -> Dict[str, float]:
    agg={}
    for r in rows:
        sym=(r["symbol"] or "").replace("/USDT:USDT","USDT").replace("/","").upper()
        if not sym: continue
        d=agg.setdefault(sym, {"cand":0.0,"pass":0.0,"alert":0.0,"rrw":0.0})
        w=_exp_decay_weight(int(r["ts"]) if r["ts"] is not None else 0)
        d["cand"]+=w
        passed = r["passed"] if "passed" in r.keys() else None
        try:
            if passed is not None and int(passed)>=min_passed_needed: d["pass"]+=w
        except Exception:
            pass
        ev=(r["event"].lower() if "event" in r.keys() and r["event"] else "")
        if ev in ("sent","alert","signal","signal_sent","telegram","notif"): d["alert"]+=w
        rr=None
        if "rr1" in r.keys() and r["rr1"] is not None:
            try: rr=float(r["rr1"])
            except Exception: rr=None
        if rr is not None and rr>=1.5: d["rrw"]+=w*min(rr,3.0)
    scored={}
    for sym,d in agg.items():
        cand=max(d["cand"],1e-9)
        pass_rate=d["pass"]/cand; alert_rate=d["alert"]/cand; rr_term=min(1.0,d["rrw"]/cand)
        score = 0.6*pass_rate + 0.3*alert_rate + 0.1*rr_term
        if cand>10.0: score*=1.05
        scored[sym]=score
    return scored

async def build_learned_watchlist(ex, settings, top_n:int=60) -> List[str]:
    db_path = _cfg(settings,"STATS_DB_PATH","data/stats.db")
    min_passed = int(_cfg(settings,"MIN_PASSED",8))
    syms=[]
    conn=_open_stats(db_path)
    if conn:
        try:
            rows=_fetch_rows(conn, days=14)
            scored=_score(rows, min_passed_needed=min_passed)
            syms=[s for s,_ in sorted(scored.items(), key=lambda kv: kv[1], reverse=True)][:top_n]
        except Exception:
            syms=[]
        finally:
            try: conn.close()
            except Exception: pass
    if syms: return syms
    try:
        from .universe import build_classic_watchlist
        return await build_classic_watchlist(ex, settings, top_n=top_n)
    except Exception:
        return ["BTCUSDT","ETHUSDT","SOLUSDT"][:top_n]
