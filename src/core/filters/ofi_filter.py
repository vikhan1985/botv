from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult

def _get(cfg, name: str, default):
    return getattr(cfg, name, default)

class OfiFilter(Filter):
    name = "ofi"

    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        """
        Анти-разворот поверх OFI:
        - порог с гистерезисом (чтобы не флипало у нулевой границы)
        - минимальный абсолют CVD (исключить "тонкий" объём)
        - при наличии серий ofi/cvd: подтверждение N барами и положительным наклоном
        """
        side = ctx.get("side_hint", "none")
        ofi = data.get("ofi", None)
        cvd = data.get("cvd", None)

        if (ofi is None) or (cvd is None) or side == "none":
            # исходная логика возвращала False, т.к. без данных нельзя подтвердить. :contentReference[oaicite:6]{index=6}
            return {"ok": False, "score": 0.0, "notes": {"ofi": ofi, "cvd": cvd, "reason": "no_data_or_side"}}

        # базовый порог (как было), + гистерезис (bps)
        base_thr = float(_get(cfg, "OFI_THRESHOLD", 0.0))
        hyst_bps = float(_get(cfg, "OFI_HYSTERESIS_BPS", 0.0))
        thr = base_thr * (1.0 + hyst_bps / 10_000.0) if base_thr > 0 else 0.0

        # минимальный абсолютный CVD (чтобы сигнал не проходил, когда накопление "тонкое")
        cvd_min_abs = float(_get(cfg, "CVD_MIN_ABS", 0.0))

        # Проверка только по последнему значению (совместимо с прежней логикой)
        if side == "long":
            ok = (float(ofi) >= thr) and (float(cvd) >= max(0.0, cvd_min_abs))
        else:
            ok = (float(ofi) <= -thr) and (float(cvd) <= -max(0.0, cvd_min_abs))

        # Если есть серии ofi/cvd, усилим анти-разворот:
        ofi_s = data.get("ofi_series")   # pd.Series | None
        cvd_s = data.get("cvd_series")   # pd.Series | None
        confirm_bars = int(_get(cfg, "OFI_CONFIRM_BARS", 1))  # 1 = как раньше (по последнему бару)
        cvd_slope_min = float(_get(cfg, "CVD_SLOPE_MIN", 0.0))  # 0 = выключено

        if ok and (confirm_bars > 1) and (ofi_s is not None):
            tail = ofi_s.tail(confirm_bars)
            if side == "long":
                ok = bool((tail >= thr).all())
            else:
                ok = bool((tail <= -thr).all())

        if ok and (cvd_s is not None) and (cvd_slope_min != 0.0):
            tail = cvd_s.tail(max(confirm_bars, 2))
            cvd_slope = float(tail.iloc[-1] - tail.iloc[0])
            if side == "long":
                ok = ok and (cvd_slope >= cvd_slope_min)
            else:
                ok = ok and (cvd_slope <= -cvd_slope_min)

        return {
            "ok": bool(ok),
            "score": 1.0 if ok else 0.0,
            "notes": {"ofi": float(ofi), "cvd": float(cvd), "thr": thr}
        }

from .base import register
register(OfiFilter)
