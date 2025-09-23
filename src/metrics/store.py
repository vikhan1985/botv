
from __future__ import annotations

import sqlite3, time
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime, timezone
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

from loguru import logger

_DB_PATH: Optional[Path] = None
_TZ = timezone.utc  # default

def _local_day(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=_TZ)
    return dt.strftime("%Y-%m-%d")

def init_stats(settings) -> None:
    """Initialize stats storage based on settings (creates DB if enabled)."""
    global _DB_PATH, _TZ
    if not getattr(settings, "STATS_ENABLED", True):
        logger.info("[STATS] disabled")
        _DB_PATH = None
        return

    tzname = getattr(settings, "STATS_TZ", "UTC")
    try:
        if ZoneInfo is not None:
            _TZ = ZoneInfo(tzname)
        else:
            _TZ = timezone.utc
        logger.info("[STATS] TZ=%s", tzname)
    except Exception as e:
        logger.warning("[STATS] bad STATS_TZ=%s, fallback UTC (%s)", tzname, e)
        _TZ = timezone.utc

    path = getattr(settings, "STATS_DB_PATH", "data/stats.db")
    _DB_PATH = Path(path)
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts INTEGER NOT NULL,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            timeframe TEXT NOT NULL,
            rr1 REAL,
            entry REAL, sl REAL, tp1 REAL, tp2 REAL,
            passed INTEGER, needed INTEGER,
            srt_ok INTEGER,
            mand_cnt INTEGER, mand_need INTEGER,
            sent INTEGER NOT NULL,
            reason TEXT
        );"""
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(date);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);")
    conn.commit()

    # --- migrations for outcomes ---
    try:
        cur.execute("PRAGMA table_info(signals)")
        cols = [r[1] for r in cur.fetchall()]
        alter = []
        if "closed" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN closed INTEGER DEFAULT 0")
        if "outcome" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN outcome TEXT")
        if "closed_ts" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN closed_ts INTEGER")
        if "tp1_hit_ts" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN tp1_hit_ts INTEGER")
        if "tp2_hit_ts" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN tp2_hit_ts INTEGER")
        if "sl_hit_ts" not in cols:
            alter.append("ALTER TABLE signals ADD COLUMN sl_hit_ts INTEGER")
        for stmt in alter:
            cur.execute(stmt)
        if alter:
            conn.commit()
            logger.info("[STATS] migrated table 'signals' with columns: %s", ", ".join(stmt.split()[-1] for stmt in alter))
        cur.execute("CREATE INDEX IF NOT EXISTS idx_signals_outcome ON signals(outcome)")
        conn.commit()
    except Exception as e:
        logger.warning("[STATS] migration failed: %s", e)

    conn.close()
    logger.info("[STATS] DB ready at %s", _DB_PATH)

def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Stats DB is not initialized or disabled")
    return sqlite3.connect(_DB_PATH)

def log_signal_event(settings, symbol: str, pack: Dict[str, Any], mand_cnt: int, mand_need: int,
                     event: str, reason: str = "") -> None:
    """Write a single signal event (sent/skipped) with context into DB."""
    if _DB_PATH is None:
        return
    try:
        ts = time.time()
        date = _local_day(ts)
        tf = pack.get("tf", "H15")
        side = pack.get("side") or "none"

        greens = pack.get("greens", {}) or {}
        notes = pack.get("notes", {}) or {}
        rr1 = notes.get("rr1")
        entry = pack.get("entry"); sl = pack.get("sl")
        tp1 = pack.get("tp1"); tp2 = pack.get("tp2")
        passed = int(pack.get("passed", 0))
        needed = int(pack.get("needed", 0))
        srt_ok = 1 if greens.get("srt") else 0
        sent = 1 if event == "sent" else 0

        with _connect() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO signals (ts,date,symbol,side,timeframe,rr1,entry,sl,tp1,tp2,passed,needed,srt_ok,mand_cnt,mand_need,sent,reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(ts), date, symbol, side, tf, rr1, entry, sl, tp1, tp2, passed, needed, srt_ok, int(mand_cnt), int(mand_need), sent, reason[:120])
            )
            conn.commit()
    except Exception as e:
        logger.warning("[STATS] log failed for %s: %s", symbol, e)

def update_outcome(row_id: int, outcome: str, closed_ts: int, tp1_ts: int|None, tp2_ts: int|None, sl_ts: int|None) -> None:
    """Mark outcome for a sent signal."""
    if _DB_PATH is None:
        return
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE signals SET closed=1, outcome=?, closed_ts=?, tp1_hit_ts=?, tp2_hit_ts=?, sl_hit_ts=? WHERE id=?",
            (outcome, int(closed_ts), tp1_ts, tp2_ts, sl_ts, int(row_id))
        )
        conn.commit()

def summarize(period: str, date_or_month: str) -> Dict[str, Any]:
    """
    period: 'day' with date YYYY-MM-DD, or 'month' with YYYY-MM
    returns aggregated stats dict
    """
    if _DB_PATH is None:
        return {"enabled": False, "total": 0}

    if period == "day":
        where = "WHERE date = ?"
        params = [date_or_month]
    elif period == "month":
        where = "WHERE substr(date,1,7) = ?"
        params = [date_or_month]
    else:
        raise ValueError("period must be 'day' or 'month'")

    with _connect() as conn:
        cur = conn.cursor()
        # totals
        cur.execute(f"SELECT COUNT(*), SUM(sent) FROM signals {where}", params)
        row = cur.fetchone() or (0, 0)
        total = row[0] or 0
        sent = row[1] or 0

        # by side among sent
        cur.execute(f"SELECT side, SUM(sent) FROM signals {where} GROUP BY side", params)
        side_sent = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

        # RR among sent
        cur.execute(f"SELECT AVG(rr1), MIN(rr1), MAX(rr1) FROM signals {where} AND sent=1", params)
        rr = cur.fetchone() or (None, None, None)

        # top symbols among sent
        cur.execute(
            f"SELECT symbol, COUNT(*) AS c FROM signals {where} AND sent=1 "
            "GROUP BY symbol ORDER BY c DESC LIMIT 5",
            params,
        )
        top = cur.fetchall()

        # top skip reasons (among not sent)
        cur.execute(
            f"SELECT reason, COUNT(*) FROM signals {where} AND sent=0 "
            "GROUP BY reason ORDER BY COUNT(*) DESC LIMIT 5",
            params,
        )
        reasons = cur.fetchall()

        # outcomes
        cur.execute(f"SELECT COUNT(*) FROM signals {where} AND sent=1 AND closed=1 AND outcome='SL'", params)
        closed_sl = int(cur.fetchone()[0] or 0)
        cur.execute(f"SELECT COUNT(*) FROM signals {where} AND sent=1 AND closed=1 AND outcome='TP1'", params)
        closed_tp1 = int(cur.fetchone()[0] or 0)
        cur.execute(f"SELECT COUNT(*) FROM signals {where} AND sent=1 AND closed=1 AND outcome='TP2'", params)
        closed_tp2 = int(cur.fetchone()[0] or 0)
        cur.execute(f"SELECT COUNT(*) FROM signals {where} AND sent=1 AND closed=0", params)
        still_open = int(cur.fetchone()[0] or 0)

    return {
        "enabled": True,
        "period": period,
        "key": date_or_month,
        "total": int(total),
        "sent": int(sent),
        "accept_rate": (sent / total) if total else 0.0,
        "sent_by_side": side_sent,
        "rr_avg": float(rr[0]) if rr and rr[0] is not None else None,
        "rr_min": float(rr[1]) if rr and rr[1] is not None else None,
        "rr_max": float(rr[2]) if rr and rr[2] is not None else None,
        "top_symbols": [(r[0], int(r[1])) for r in top],
        "top_skip_reasons": [(r[0] or "", int(r[1])) for r in reasons],
        "closed_sl": closed_sl,
        "closed_tp1": closed_tp1,
        "closed_tp2": closed_tp2,
        "still_open": still_open,
    }

def format_report(summary: Dict[str, Any]) -> str:
    if not summary.get("enabled", False):
        return "📊 Статистика выключена."
    period = summary["period"]
    key = summary["key"]
    total = summary["total"]; sent = summary["sent"]
    rate = f"{(summary['accept_rate']*100):.1f}%"
    rr_avg = "—" if summary["rr_avg"] is None else f"{summary['rr_avg']:.2f}"
    rr_min = "—" if summary["rr_min"] is None else f"{summary['rr_min']:.2f}"
    rr_max = "—" if summary["rr_max"] is None else f"{summary['rr_max']:.2f}"
    top_syms = ", ".join(f"{s}({c})" for s,c in summary["top_symbols"]) or "—"
    reasons = ", ".join(f"{r or 'other'}({c})" for r,c in summary["top_skip_reasons"]) or "—"
    by_side = summary.get("sent_by_side", {})
    long_n = by_side.get("long", 0); short_n = by_side.get("short", 0)

    lines = [
        f"📊 <b>{'День' if period == 'day' else 'Месяц'}:</b> <code>{key}</code>",
        f"Всего сетапов: <b>{total}</b> • Отправлено: <b>{sent}</b> • Принятие: <b>{rate}</b>",
        f"RR1 отправленных: avg <b>{rr_avg}</b> • min {rr_min} • max {rr_max}",
        f"LONG/SHORT: <b>{long_n}</b> / <b>{short_n}</b>",
        f"Топ-символы (отправлено): {top_syms}",
        f"Причины отказов: {reasons}",
        f"Закрытия: SL <b>{summary.get('closed_sl',0)}</b> • TP1 <b>{summary.get('closed_tp1',0)}</b> • TP2 <b>{summary.get('closed_tp2',0)}</b> • Открыты <b>{summary.get('still_open',0)}</b>",
    ]
    return "\n".join(lines)
