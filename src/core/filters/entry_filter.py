from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult
from ...indicators.ema import ema

def _entry_rule_ok(df_ltf, side: str, vwap_val: float | None, bars: int,
                   require_both: bool, ema_gap_min_bps: float) -> bool:
    if df_ltf is None or df_ltf.empty:
        return False

    close_s = df_ltf["close"]
    e21 = float(ema(close_s, 21).iloc[-1])
    e50 = float(ema(close_s, 50).iloc[-1])
    c_last = float(close_s.iloc[-1])

    # базовая логика (как было): EMA или VWAP подтверждают вход. :contentReference[oaicite:3]{index=3}
    ema_ok = (e21 > e50 and c_last > e21) if side == "long" else (e21 < e50 and c_last < e21)

    # анти-шум: требуем минимальный разрыв между EMA21 и EMA50
    if ema_ok and ema_gap_min_bps > 0:
        base = abs(e50) if e50 != 0 else 1.0
        gap_bps = abs(e21 - e50) / base * 10_000.0
        if gap_bps < ema_gap_min_bps:
            ema_ok = False

    vwap_ok = False
    if vwap_val is not None:
        last_closes = close_s.tail(bars)
        vwap_ok = bool((last_closes > vwap_val).all()) if side == "long" else bool((last_closes < vwap_val).all())

    if require_both:
        return bool(ema_ok and vwap_ok)
    else:
        return bool(ema_ok or vwap_ok)

class EntryFilter(Filter):
    name = "entry"

    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        # выключение фильтра (как было): сразу True. :contentReference[oaicite:4]{index=4}
        if not bool(getattr(cfg, "ENTRY_CONFIRM", False)):
            return {"ok": True, "score": 1.0, "notes": {"reason": "disabled"}}

        side = ctx.get("side_hint", "none")
        vwap_val = data.get("vwap", None)

        bars = int(getattr(cfg, "ENTRY_BARS", 2))
        tfs = [t.lower() for t in getattr(cfg, "ENTRY_TFS", ["5m", "15m"])]
        require_any = bool(getattr(cfg, "ENTRY_REQUIRE_ANY", True))

        # новые ключи (обратно-совместимо: по умолчанию выключено)
        require_both = bool(getattr(cfg, "ENTRY_REQUIRE_BOTH", False))  # требовать EMA и VWAP одновременно
        ema_gap_min_bps = float(getattr(cfg, "ENTRY_EMA_GAP_MIN_BPS", 0.0))  # минимум "зазора" между EMA21 и EMA50

        checks = []
        for tf in tfs:
            if tf == "5m":
                checks.append(_entry_rule_ok(
                    data.get("ohlcv_5m"), side, vwap_val, bars, require_both, ema_gap_min_bps
                ))
            elif tf == "15m":
                checks.append(_entry_rule_ok(
                    data.get("ohlcv_15m"), side, vwap_val, bars, require_both, ema_gap_min_bps
                ))

        ok = True if not checks else (any(checks) if require_any else all(checks))
        return {
            "ok": bool(ok),
            "score": 1.0 if ok else 0.0,
            "notes": {"tfs": tfs, "bars": bars, "require_both": require_both, "ema_gap_min_bps": ema_gap_min_bps}
        }

from .base import register
register(EntryFilter)
