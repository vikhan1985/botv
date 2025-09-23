from __future__ import annotations
from typing import Any, Dict
from .contracts import DataSlice
from .filters.base import REGISTRY
from .filters import atr_filter, trend_filter, vwap_filter, oi_filter, ofi_filter, sr_filter, adx_filter, entry_filter, candle_filter  # noqa: F401
from ..indicators.ema import ema  # для уровней
from ..indicators.atr import atr_wilder

def _ema_zone(last_close_s, fast: int, mid: int) -> tuple[float, float]:
    e1 = ema(last_close_s, fast).iloc[-1]
    e2 = ema(last_close_s, mid).iloc[-1]
    return (min(e1, e2), max(e1, e2))

def _clamp_sl_by_pct(entry: float, sl_raw: float, side: str, sl_min_pct: float, sl_max_pct: float) -> float:
    sl_min_pct = sl_min_pct or 0.6; sl_max_pct = sl_max_pct or 1.0
    if sl_min_pct > sl_max_pct: sl_min_pct, sl_max_pct = sl_max_pct, sl_min_pct
    dist = (entry - sl_raw) if side == "long" else (sl_raw - entry)
    if dist <= 0:
        dist = entry * (sl_min_pct / 100.0)
        sl_raw = entry - dist if side == "long" else entry + dist
    min_dist = entry * (sl_min_pct / 100.0)
    max_dist = entry * (sl_max_pct / 100.0)
    dist = max(min_dist, min(max_dist, dist))
    return entry - dist if side == "long" else entry + dist

def _compute_structural_levels(data: DataSlice, cfg, side: str, atr_sig_last: float, vwap_val: float | None):
    df_sig = data["ohlcv_sig"]
    last = float(df_sig["close"].iloc[-1])
    look_swing = getattr(cfg, "SWING_LOOKBACK_H15", 6)
    ema_lo, ema_hi = _ema_zone(df_sig["close"], cfg.EMA_FAST, cfg.EMA_MID)
    sw_low = float(df_sig["low"].tail(look_swing).min())
    sw_high = float(df_sig["high"].tail(look_swing).max())
    sl_buffer_bps = int(getattr(cfg, "SL_BUFFER_BPS", 5))
    sl_min_pct = float(getattr(cfg, "SL_MIN_PCT", 0.6)); sl_max_pct = float(getattr(cfg, "SL_MAX_PCT", 1.0))
    def _add_buffer(level: float, side: str, bps: int) -> float:
        k = (bps or 0) / 10_000.0
        return level * (1 - k) if side == "long" else level * (1 + k)
    if side == "long":
        cands = []
        if sw_low < last: cands.append(sw_low)
        if ema_lo < last: cands.append(ema_lo)
        if (vwap_val is not None) and (vwap_val < last):
            cands.append(vwap_val - 0.25 * atr_sig_last)
        sl_raw = max(cands) if cands else last * (1 - float(getattr(cfg, "SL_PCT", 0.8)) / 100.0)
        sl_raw = _add_buffer(sl_raw, side, sl_buffer_bps)
    else:
        cands = []
        if sw_high > last: cands.append(sw_high)
        if ema_hi > last: cands.append(ema_hi)
        if (vwap_val is not None) and (vwap_val > last):
            cands.append(vwap_val + 0.25 * atr_sig_last)
        sl_raw = min(cands) if cands else last * (1 + float(getattr(cfg, "SL_PCT", 0.8)) / 100.0)
        sl_raw = _add_buffer(sl_raw, side, sl_buffer_bps)
    sl = _clamp_sl_by_pct(last, sl_raw, side, sl_min_pct, sl_max_pct)

    tp_mode = str(getattr(cfg, "TP_MODE", "R_MULTI")).upper()
    if tp_mode == "R_MULTI":
        tp1_r = float(getattr(cfg, "TP1_R_MULT", 1.2)); tp2_r = float(getattr(cfg, "TP2_R_MULT", 2.0))
        R = (last - sl) if side == "long" else (sl - last)
        tp1 = last + (tp1_r * R if side == "long" else -tp1_r * R)
        tp2 = last + (tp2_r * R if side == "long" else -tp2_r * R)
    elif tp_mode == "ATR_MULTI":
        tp1_m = float(getattr(cfg, "ATR_TP1_MULT", 1.0)); tp2_m = float(getattr(cfg, "ATR_TP2_MULT", 1.8))
        tp1 = last + (tp1_m * atr_sig_last if side == "long" else -tp1_m * atr_sig_last)
        tp2 = last + (tp2_m * atr_sig_last if side == "long" else -tp2_m * atr_sig_last)
    else:
        tp1_pct = float(getattr(cfg, "TP1_PCT", 1.0)); tp2_pct = float(getattr(cfg, "TP2_PCT", 1.9))
        tp1 = last * (1 + tp1_pct / 100.0) if side == "long" else last * (1 - tp1_pct / 100.0)
        tp2 = last * (1 + tp2_pct / 100.0) if side == "long" else last * (1 - tp2_pct / 100.0)
    notes = {"swing_low": sw_low, "swing_high": sw_high, "ema_low": ema_lo, "ema_high": ema_hi, "vwap": data.get("vwap")}
    return float(last), float(sl), float(tp1), float(tp2), notes

async def evaluate_strategy_h15(symbol: str, data: DataSlice, cfg) -> Dict[str, Any]:
    # 0) Ликвидность
    liq_ok = bool(data.get("liq_ok", False)); liq_notes = data.get("liq_notes", {})

    # 1) Гоним фильтры по реестру (порядок важен: тренд первым — даёт side)
    ctx: dict[str, Any] = {}
    order = ["trend","vwap","oi","ofi","sr","adx","candle","atr","entry"]  # можно переставлять; trend должен быть раньше SR/VWAP/entry
    results: dict[str, Any] = {}
    for name in order:
        f = REGISTRY[name]
        results[name] = await f.run(symbol, data, cfg, ctx)

    # 2) Извлекаем флаги
    greens = {k: bool(v.get("ok")) for k, v in results.items()}
    side_hint = (results.get("trend", {}).get("notes") or {}).get("side_hint", "none")

    # 3) near-SR и fallback (знают о других флагах)
    sr_notes = (results.get("sr") or {}).get("notes") or {}
    dist_bps = float(sr_notes.get("dist_bps") or 1e9)
    # near-SR
    near_bps = int(getattr(cfg, "SR_NEAR_BPS", 0) or 0)
    if near_bps > 0 and side_hint in ("long","short"):
        needs = set(getattr(cfg, "SR_NEAR_NEEDS", ["ofi","adx"]))
        flags = {"ofi": greens.get("ofi", False), "adx": greens.get("adx", False), "vwap": greens.get("vwap", False), "trend": greens.get("trend", False)}
        needs_ok = all(flags.get(k, False) for k in needs)
        if (not greens["sr"]) and (dist_bps <= near_bps) and needs_ok:
            greens["sr"] = True
    # fallback SRT→SR
    fb_bps = int(getattr(cfg, "SRT_FALLBACK_BPS", 0) or 0)
    if (not greens["sr"]) and (dist_bps <= fb_bps) and greens.get("vwap") and greens.get("adx"):
        greens["sr"] = True

    # 4) SRT ворота
    srt_mode = str(getattr(cfg, "SRT_MODE", "STRICT")).upper()
    if srt_mode == "RELAX":
        vote = (1 if greens.get("sr") else 0) + (1 if greens.get("vwap") else 0) + (1 if greens.get("adx") else 0)
        srt_ok = bool(greens.get("trend") and (vote >= 2))
    else:
        srt_ok = bool(greens.get("sr") and greens.get("trend") and (greens.get("vwap") or greens.get("adx")))
    greens["srt"] = srt_ok

    # 5) Mandatory gate
    mandatory = getattr(cfg, "MANDATORY_FILTERS", [])
    req_n = int(getattr(cfg, "MANDATORY_REQUIRE_N", 0) or 0)
    if mandatory and req_n > 0:
        cnt = sum(1 for name in mandatory if (name == "liquidity" and liq_ok) or greens.get(name, False))
        if cnt < req_n:
            return None

    # 6) Подсчёт силы (9 базовых без srt): включая entry
    core_keys = ("liquidity","atr","trend","vwap","oi","ofi","sr","adx","entry")
    passed = int(sum(1 for k in core_keys if (liq_ok if k=="liquidity" else greens.get(k, False))))
    needed = len(core_keys)

    # Базовые обязательные 3
    if not (liq_ok and greens.get("atr") and greens.get("trend")):
        return {
            "symbol": symbol, "side": "none", "greens": {"liquidity": liq_ok, **greens},
            "passed": passed, "needed": needed,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "notes": {
                **(results.get("atr", {}).get("notes") or {}),
                **(results.get("trend", {}).get("notes") or {}),
                "vwap": data.get("vwap"), "oi_delta_pct": data.get("oi_change_pct"), "ofi": data.get("ofi"),
                **(liq_notes or {})
            }
        }

    if (passed < int(getattr(cfg, 'TOTAL_FILTERS_REQUIRED', 7) or 7)) or (not greens["srt"]) or (not greens.get("entry", True)):
        return {
            "symbol": symbol, "side": "none", "greens": {"liquidity": liq_ok, **greens},
            "passed": passed, "needed": needed,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "notes": {
                "reason": "gate_fail", "srt_ok": greens["srt"], "entry_ok": greens.get("entry", True),
                **(results.get("atr", {}).get("notes") or {}),
                **(results.get("trend", {}).get("notes") or {}),
                "vwap": data.get("vwap"), "oi_delta_pct": data.get("oi_change_pct"), "ofi": data.get("ofi"),
                **(liq_notes or {})
            }
        }

    # 7) Сторона
    side = "long" if side_hint == "long" else ("short" if side_hint == "short" else "none")
    if side == "none":
        return {
            "symbol": symbol, "side": "none", "greens": {"liquidity": liq_ok, **greens},
            "passed": passed, "needed": needed,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "notes": {"reason": "no_side"}
        }

    # 8) Уровни и RR
    atr_sig_last = float(results.get("atr", {}).get("notes", {}).get("atr_sig_pct", 0))  # тут проценты, нужен ATR abs
    # исправим: возьмём настоящий ATR 1h
    atr_sig_abs = ctx.get("atr_sig_last", None)
    if atr_sig_abs is None:
        atr_sig_abs = float(atr_wilder(data["ohlcv_sig"]["high"], data["ohlcv_sig"]["low"], data["ohlcv_sig"]["close"], 14).iloc[-1])

    entry_price, sl, tp1, tp2, lvl_notes = _compute_structural_levels(data, cfg, side, float(atr_sig_abs), data.get("vwap"))
        # RR с учётом комиссий и проскальзывания (если заданы)
    dist_up = abs(tp1 - entry_price) / max(1e-9, entry_price)
    dist_dn = abs(entry_price - sl) / max(1e-9, entry_price)
    rr1_raw = (dist_up / max(1e-9, dist_dn)) if (entry_price != sl) else 0.0
    fee_bps = float(getattr(cfg, 'TAKER_FEE_BPS', 0.0) or 0.0)
    slip_bps = float(getattr(cfg, 'SLIPPAGE_BPS', 0.0) or 0.0)
    if fee_bps > 0.0 or slip_bps > 0.0:
        fee_total = 2.0 * fee_bps / 10000.0  # open+close
        slip_total = 2.0 * slip_bps / 10000.0  # entry+exit
        profit_eff = max(0.0, dist_up - fee_total - slip_total)
        risk_eff = max(1e-9, dist_dn + slip_total)
        rr1 = profit_eff / risk_eff
    else:
        rr1 = rr1_raw


    # адаптивный RR (опционально)
    min_rr = float(getattr(cfg, 'MIN_RR1', 1.8))
    threshold = min_rr
    if rr1 < threshold:
        return {
            "symbol": symbol, "side": "none", "greens": {"liquidity": liq_ok, **greens},
            "passed": passed, "needed": needed,
            "entry": None, "sl": None, "tp1": None, "tp2": None,
            "notes": {"rr1": rr1, "rr_threshold": threshold}
        }

    notes = {
        **(results.get("atr", {}).get("notes") or {}),
        **(results.get("trend", {}).get("notes") or {}),
        "vwap": data.get("vwap"), "oi_delta_pct": data.get("oi_change_pct"), "ofi": data.get("ofi"),
        "rr1": rr1, **lvl_notes, **(liq_notes or {})
    }
    # штамп последнего бара 1h
    notes["bar_ts"] = int(data["ohlcv_sig"]["ts"].iloc[-1])

    return {
        "symbol": symbol,
        "side": side,
        "greens": {"liquidity": liq_ok, **greens},
        "passed": passed,
        "needed": needed,
        "entry": float(entry_price),
        "sl": float(sl),
        "tp1": float(tp1),
        "tp2": float(tp2),
        "notes": notes
    }
