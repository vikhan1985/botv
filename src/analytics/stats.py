# -*- coding: utf-8 -*-
# src/analytics/stats.py

from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any, Tuple

import pytz
import pandas as pd

from ..data.klines import fetch_ohlcv_df
from ..data.binance_client import normalize_symbol


@dataclass
class SignalRecord:
    symbol: str
    side: str                   # 'long'|'short'
    ts_ms: int                  # время сигнала (ms) — бар BASE TF
    base_tf: str                # базовый ТФ ('30m', '1h', ...)
    entry: float
    sl: float
    tp1: float
    tp2: float
    passed: int                 # сколько фильтров из 8
    rr1: float                  # RR к TP1

    # Времена достижений уровней (если были)
    tp1_ts_ms: Optional[int] = None
    tp2_ts_ms: Optional[int] = None
    sl_ts_ms: Optional[int] = None

    # Итоговый исход по самому раннему событию
    outcome: str = "pending"    # 'pending'|'tp1'|'tp2'|'sl'|'none'
    outcome_ts_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "SignalRecord":
        return cls(**d)


def _fmt_duration(seconds: Optional[float]) -> str:
    """Человекочитаемая длительность: 34м, 1ч20м, 2д03ч."""
    if seconds is None or seconds <= 0:
        return "-"
    m = int(seconds // 60)
    if m < 60:
        return f"{m}м"
    h = m // 60
    rm = m % 60
    if h < 48:
        return f"{h}ч{rm:02d}м"
    d = h // 24
    rh = h % 24
    return f"{d}д{rh:02d}ч"


class StatsStore:
    """
    Копит записи сигналов, дооценивает исходы по OHLCV и строит ежедневный отчёт.
    """
    def __init__(self, dir_path: str, tz_name: str, eval_lookahead_hours: int = 48) -> None:
        self.dir = dir_path
        os.makedirs(self.dir, exist_ok=True)
        self.tz = pytz.timezone(tz_name)
        self.lookahead_hours = int(eval_lookahead_hours)
        self._records: List[SignalRecord] = []

    # ---------- persist ----------
    def _day_key(self, dt_local: datetime) -> str:
        return dt_local.strftime("%Y-%m-%d")

    def _paths_for_day(self, day_key: str) -> Tuple[str, str]:
        return (
            os.path.join(self.dir, f"{day_key}.json"),
            os.path.join(self.dir, f"{day_key}.csv"),
        )

    def append_signal(self, rec: SignalRecord) -> None:
        self._records.append(rec)

    def flush_today(self) -> None:
        if not self._records:
            return
        df = pd.DataFrame([r.to_dict() for r in self._records])
        df["ts_local"] = df["ts_ms"].apply(lambda x: datetime.fromtimestamp(x / 1000, self.tz))
        for day_key, part in df.groupby(df["ts_local"].dt.strftime("%Y-%m-%d")):
            jpath, cpath = self._paths_for_day(day_key)
            js = part.drop(columns=["ts_local"]).to_dict(orient="records")
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump(js, f, ensure_ascii=False, indent=2)
            part.to_csv(cpath, index=False)

    # ---------- outcomes ----------
    async def evaluate_outcomes_for_pending(self, ex) -> None:
        """
        Для всех pending находим времена первого касания TP1/TP2/SL и итоговый исход (самое раннее событие).
        """
        now_utc = datetime.now(timezone.utc)
        pending = [r for r in self._records if r.outcome == "pending"]
        if not pending:
            return

        for r in pending:
            try:
                sym = normalize_symbol(r.symbol)
                start_ms = r.ts_ms
                end_ms = int(
                    (min(
                        now_utc,
                        datetime.fromtimestamp(r.ts_ms / 1000, timezone.utc) + timedelta(hours=self.lookahead_hours)
                    ).timestamp()) * 1000
                )

                df = await fetch_ohlcv_df(ex, sym, r.base_tf, limit=800)
                if df is None or df.empty:
                    continue
                df = df[(df["ts"] >= start_ms) & (df["ts"] <= end_ms)]
                if df.empty:
                    continue

                # Ищем первые касания
                for _, row in df.iterrows():
                    t = int(row["ts"])
                    h = float(row["high"])
                    l = float(row["low"])

                    if r.side == "long":
                        if r.tp1_ts_ms is None and h >= r.tp1:
                            r.tp1_ts_ms = t
                        if r.tp2_ts_ms is None and h >= r.tp2:
                            r.tp2_ts_ms = t
                        if r.sl_ts_ms is None and l <= r.sl:
                            r.sl_ts_ms = t
                    else:  # short
                        if r.tp1_ts_ms is None and l <= r.tp1:
                            r.tp1_ts_ms = t
                        if r.tp2_ts_ms is None and l <= r.tp2:
                            r.tp2_ts_ms = t
                        if r.sl_ts_ms is None and h >= r.sl:
                            r.sl_ts_ms = t

                # Итог — самое раннее из произошедших
                candidates = []
                if r.tp2_ts_ms is not None:
                    candidates.append(("tp2", r.tp2_ts_ms))
                if r.tp1_ts_ms is not None:
                    candidates.append(("tp1", r.tp1_ts_ms))
                if r.sl_ts_ms is not None:
                    candidates.append(("sl", r.sl_ts_ms))

                if candidates:
                    outcome, ts = min(candidates, key=lambda x: x[1])
                    r.outcome = outcome
                    r.outcome_ts_ms = ts
                else:
                    # в окне не случилось ничего — пусть повисит pending (или станет 'none' позже)
                    pass

            except Exception:
                continue

    # ---------- reporting ----------
    def build_daily_report_text(self, day_local: Optional[datetime] = None) -> str:
        """
        Формат пользователя:
        📊 Ежедневный отчёт YYYY-MM-DD
        Всего сигналов: N

        • BTCUSDT: TP1 + (1ч20м), TP2 -, SL -
        ...
        """
        if day_local is None:
            day_local = datetime.now(self.tz)
        day_key = self._day_key(day_local)
        jpath, _ = self._paths_for_day(day_key)
        if not os.path.exists(jpath):
            return f"📊 Ежедневный отчёт {day_key}\nВсего сигналов: 0"

        with open(jpath, "r", encoding="utf-8") as f:
            rows = json.load(f)
        df = pd.DataFrame(rows)
        if df.empty:
            return f"📊 Ежедневный отчёт {day_key}\nВсего сигналов: 0"

        total = len(df)

        # Время до касания (в секундах) для каждого уровня
        def diffs(col_ts: str, row) -> Optional[float]:
            try:
                t1 = row.get("ts_ms"); t2 = row.get(col_ts)
                if t1 is None or t2 is None:
                    return None
                return max(0.0, (float(t2) - float(t1)) / 1000.0)
            except Exception:
                return None

        df["tt_tp1"] = df.apply(lambda r: diffs("tp1_ts_ms", r), axis=1)
        df["tt_tp2"] = df.apply(lambda r: diffs("tp2_ts_ms", r), axis=1)
        df["tt_sl"]  = df.apply(lambda r: diffs("sl_ts_ms",  r), axis=1)

        lines = [f"📊 Ежедневный отчёт {day_key}", f"Всего сигналов: {total}", ""]

        for sym, part in df.groupby("symbol"):
            tp1_hit = part["tp1_ts_ms"].notna().any()
            tp2_hit = part["tp2_ts_ms"].notna().any()
            sl_hit  = part["sl_ts_ms"].notna().any()

            tp1_med = _fmt_duration(part["tt_tp1"].dropna().median()) if tp1_hit else "-"
            tp2_med = _fmt_duration(part["tt_tp2"].dropna().median()) if tp2_hit else "-"
            sl_med  = _fmt_duration(part["tt_sl"].dropna().median())  if sl_hit  else "-"

            line = (
                f"• {sym}: "
                f"TP1 {'+' if tp1_hit else '-'}{'' if not tp1_hit else f' ({tp1_med})'}, "
                f"TP2 {'+' if tp2_hit else '-'}{'' if not tp2_hit else f' ({tp2_med})'}, "
                f"SL {'+' if sl_hit  else '-'}{'' if not sl_hit  else f' ({sl_med})'}"
            )
            lines.append(line)

        return "\n".join(lines)

    async def send_daily_report(self, tg) -> None:
        if tg is None:
            return
        await tg.send_text(self.build_daily_report_text())
