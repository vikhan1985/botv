from __future__ import annotations

from typing import Any, Dict

import numpy as np

from ..contracts import Filter, DataSlice, FilterResult
from .base import register
from .log_utils import log_filter, fmt_bps, fmt_float


class VwapFilter(Filter):
    """
    Enhanced VWAP filter with confirmation bars, minimum bars logic,
    and extended features for card display.
    """

    name = "vwap"

    async def run(self, symbol: str, data: DataSlice, cfg: Any, ctx: Dict[str, Any]) -> FilterResult:
        # Feature flag check
        if not bool(getattr(cfg, "VWAP_ENABLED", True)):
            log_filter("VWAP", symbol, None, reason="feature_flag_off")
            return {
                "ok": True,
                "score": 0.0,
                "notes": {
                    "disabled": True,
                    "reason": "feature_flag_off",
                },
            }

        df_sig = data.get("ohlcv_sig")
        if df_sig is None or getattr(df_sig, "empty", True):
            reason = "no_data"
            log_filter("VWAP", symbol, False, reason=reason)
            return {"ok": False, "score": 0.0, "notes": {"reason": reason}}

        # Безопасное получение исторических данных
        df_hist = data.get("ohlcv_hist")
        if df_hist is None:
            df_hist = df_sig

        vwap_val = data.get("vwap", None)
        vctx = (data.get("vwap_ctx") or {}) if isinstance(data, dict) else {}

        anchor = str(vctx.get("anchor", getattr(cfg, "VWAP_ANCHOR", "day"))).lower()
        timeframe = str(vctx.get("tf", getattr(cfg, "VWAP_TIMEFRAME", "5m"))).lower()
        price_source = str(vctx.get("src", getattr(cfg, "VWAP_PRICE_SOURCE", "hlc3"))).lower()

        if vwap_val is None:
            reason = "no_vwap_data"
            log_filter(
                "VWAP", symbol, False,
                tf=timeframe, anchor=anchor, src=price_source,
                reason=reason,
            )
            return {"ok": False, "score": 0.0, "notes": {"reason": reason}}

        # Get configuration parameters
        dev_thr_bps = float(getattr(cfg, "VWAP_DEV_BPS_MIN", 100.0))
        confirm_bars = int(getattr(cfg, "VWAP_CONFIRM_BARS", 2))
        min_bars = int(getattr(cfg, "VWAP_MIN_BARS", 12))

        # Extended VWAP parameters
        near_bps = float(getattr(cfg, "VWAP_NEAR_BPS", 60.0))
        slope_window = int(getattr(cfg, "VWAP_SLOPE_WINDOW_BARS", 6))
        slope_min_bps = float(getattr(cfg, "VWAP_SLOPE_MIN_BPS_PER_BAR", 2.0))
        cross_lookback = int(getattr(cfg, "VWAP_CROSS_LOOKBACK_BARS", 20))
        log_extended = bool(getattr(cfg, "VWAP_LOG_EXTENDED", True))

        # Last price
        last_close = float(df_sig["close"].iloc[-1])
        vwap_val_float = float(vwap_val)

        # Absolute deviation from VWAP in bps
        dev_abs_bps = abs((last_close - vwap_val_float) / vwap_val_float) * 10_000.0
        # Signed deviation for direction
        signed_dev_bps = ((last_close - vwap_val_float) / vwap_val_float) * 10_000.0

        # Basic VWAP deviation check
        vwap_ok = dev_abs_bps >= dev_thr_bps

        # VWAP_MIN_BARS logic
        min_bars_ok = True
        if min_bars > 0:
            if timeframe == "1d":
                current_date = df_sig.index[-1].date()
                day_bars = df_sig[df_sig.index.date == current_date]
                min_bars_ok = len(day_bars) >= min_bars
            else:
                min_bars_ok = len(df_sig) >= min_bars

        # VWAP_CONFIRM_BARS logic - FIXED VERSION
        confirm_ok = True
        if confirm_bars > 0 and len(df_sig) >= confirm_bars + 1:
            # Get recent bars excluding current bar (use only completed bars)
            recent_data = df_sig.iloc[-(confirm_bars + 1):-1]  # Exclude current bar

            # Determine current side
            current_side = last_close < vwap_val_float  # True = below VWAP (long), False = above (short)

            # Check if all confirmation bars are on the same side
            all_same_side = True
            for i in range(len(recent_data)):
                bar_close = float(recent_data["close"].iloc[i])
                # Use each bar's own close price for comparison - FIXED
                bar_side = bar_close < vwap_val_float
                if bar_side != current_side:
                    all_same_side = False
                    break

            confirm_ok = all_same_side
        elif confirm_bars > 0:
            # Not enough bars for confirmation
            confirm_ok = False

        # Final result
        ok = vwap_ok and min_bars_ok and confirm_ok

        # ========== EXTENDED VWAP FEATURES ==========

        # 1. Above/Below position - исправленная логика
        if abs(signed_dev_bps) < 0.1:  # практически на VWAP
            position = "At VWAP"
        else:
            position = "Above" if signed_dev_bps > 0 else "Below"

        # 2. Near detection
        near_detected = abs(signed_dev_bps) < near_bps
        if near_detected and position != "At VWAP":
            position = f"Near {position}"

        # 3. VWAP Slope calculation - улучшенная логика с безопасным доступом
        slope_direction = "flat"  # default
        slope_value = 0.0
        try:
            if slope_window >= 2 and len(df_hist) >= slope_window:
                # Используем исторические данные VWAP если доступны
                vwap_hist = data.get("vwap_hist")
                if vwap_hist is not None and len(vwap_hist) >= slope_window:
                    # Используем реальные исторические значения VWAP
                    recent_vwap = vwap_hist.tail(slope_window).values
                else:
                    # Fallback: используем типичные цены как приближение VWAP
                    typical_prices = (df_hist["high"] + df_hist["low"] + df_hist["close"]) / 3.0
                    recent_vwap = typical_prices.iloc[-slope_window:].values

                # Calculate linear regression slope
                x = np.arange(len(recent_vwap))
                slope = np.polyfit(x, recent_vwap, 1)[0]

                # Convert to bps per bar relative to current VWAP
                slope_bps_per_bar = (slope / vwap_val_float) * 10_000.0
                slope_value = slope_bps_per_bar

                # Determine direction with threshold
                if abs(slope_bps_per_bar) >= slope_min_bps:
                    slope_direction = "up" if slope_bps_per_bar > 0 else "down"
                else:
                    slope_direction = "flat"
        except Exception:
            slope_direction = "flat"

        # 4. Cross detection (last time price crossed VWAP)
        cross_bars_ago = None
        cross_type = None
        current_side = last_close > vwap_val_float  # True = above, False = below

        # Look back through recent bars to find crossover
        for i in range(1, min(cross_lookback + 1, len(df_hist))):
            idx = -1 - i
            if idx < -len(df_hist):  # bounds check
                break

            hist_close = float(df_hist["close"].iloc[idx])
            hist_side = hist_close > vwap_val_float

            if hist_side != current_side:
                cross_bars_ago = i
                cross_type = "above_to_below" if current_side else "below_to_above"
                break

        # Форматирование cross информации
        if cross_bars_ago is not None:
            cross_str = f"{cross_bars_ago} bar{'s' if cross_bars_ago > 1 else ''} ago"
        else:
            cross_str = f"over {cross_lookback} bars"

        # ========== LOGGING & NOTES ==========

        # Determine reason
        if not ok:
            reason_parts = []
            if not vwap_ok:
                reason_parts.append(f"dev_{dev_abs_bps:.0f}bps_below_{dev_thr_bps}bps")
            if not min_bars_ok:
                reason_parts.append("min_bars_not_met")
            if not confirm_ok:
                reason_parts.append("confirm_bars_failed")
            reason = ";".join(reason_parts)
        else:
            reason = "ok"

        # Side hint for strategy
        side_hint = "long" if last_close < vwap_val_float else "short"

        # Extended logging if enabled
        if log_extended:
            log_filter(
                "VWAP", symbol, ok,
                tf=timeframe,
                anchor=anchor,
                src=price_source,
                vwap=fmt_float(vwap_val_float, 4),
                close=fmt_float(last_close, 4),
                dev_bps=fmt_bps(signed_dev_bps),
                thr_bps=dev_thr_bps,
                confirm_bars=confirm_bars,
                min_bars=min_bars,
                side=side_hint,
                position=position,
                slope=slope_direction,
                cross=cross_str,
                near=near_detected,
                reason=reason,
            )
        else:
            # Standard logging
            log_filter(
                "VWAP", symbol, ok,
                tf=timeframe,
                anchor=anchor,
                src=price_source,
                vwap=fmt_float(vwap_val_float, 4),
                close=fmt_float(last_close, 4),
                dev_bps=fmt_bps(dev_abs_bps),
                thr_bps=dev_thr_bps,
                confirm_bars=confirm_bars,
                min_bars=min_bars,
                side=side_hint,
                reason=reason,
            )

        notes: Dict[str, Any] = {
            "vwap": vwap_val_float,
            "close": last_close,
            "vwap_dev_bps": float(dev_abs_bps),
            "vwap_signed_dev_bps": float(signed_dev_bps),
            "thr_bps": float(dev_thr_bps),
            "confirm_bars": confirm_bars,
            "min_bars": min_bars,
            "side_hint": side_hint,
            "vwap_ok": vwap_ok,
            "min_bars_ok": min_bars_ok,
            "confirm_ok": confirm_ok,
            "reason": reason,
            # Extended features for card display
            "vwap_position": position,
            "vwap_slope": slope_direction,
            "vwap_slope_value": float(slope_value),
            "vwap_cross": cross_str,
            "vwap_near": near_detected,
            "vwap_cross_type": cross_type,
        }

        return {
            "ok": ok,
            "score": 1.0 if ok else 0.0,
            "notes": notes,
        }


register(VwapFilter)
