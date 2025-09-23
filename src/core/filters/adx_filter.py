from __future__ import annotations
from ..contracts import Filter, DataSlice, FilterResult
from ...indicators.adx import adx

def _get(cfg, name: str, default):
    # безопасное чтение, чтобы не падать если ключа нет в config.yaml
    return getattr(cfg, name, default)

class AdxFilter(Filter):
    name = "adx"

    async def run(self, symbol: str, data: DataSlice, cfg, ctx) -> FilterResult:
        """
        Анти-разворот:
        - ADX >= ADX_H1_MIN (жёсткий базовый уровень силы тренда)
        - при ADX_REQUIRE_DIRECTION=True требуем доминирование +DI/-DI со
          "запасом" ADX_DI_MARGIN_BPS (базово 0 bps = выключено)
        - ADX растёт за последние ADX_LOOKBACK_SLOPE баров на не меньше ADX_SLOPE_MIN
        """
        df_htf = data["ohlcv_htf"]
        adx_val, plus_di, minus_di = adx(
            df_htf["high"], df_htf["low"], df_htf["close"],
            _get(cfg, "ADX_PERIOD", 14)
        )  # текущая реализация у вас уже так и делает. :contentReference[oaicite:1]{index=1}

        adx_last = float(adx_val.iloc[-1])
        plus_last = float(plus_di.iloc[-1])
        minus_last = float(minus_di.iloc[-1])

        ok = adx_last >= _get(cfg, "ADX_H1_MIN", 18.0)

        # Требовать совпадение направления (доминирование DI)
        if bool(_get(cfg, "ADX_REQUIRE_DIRECTION", True)):
            side = ctx.get("side_hint", "none")
            di_margin_bps = float(_get(cfg, "ADX_DI_MARGIN_BPS", 0.0))
            # margin_bps=25 означает 0.25%. Пересчёт в долю:
            margin = di_margin_bps / 10_000.0

            if side == "long":
                ok = ok and (plus_last > minus_last * (1.0 + margin))
            elif side == "short":
                ok = ok and (minus_last > plus_last * (1.0 + margin))

        # ADX должен иметь положительный наклон (избегаем затухания/разворота)
        lookback = int(_get(cfg, "ADX_LOOKBACK_SLOPE", 3))
        slope_min = float(_get(cfg, "ADX_SLOPE_MIN", 0.0))  # 0 = выключено
        if lookback > 1 and slope_min > 0.0 and len(adx_val) >= lookback + 1:
            adx_seg = adx_val.tail(lookback)
            adx_slope = float(adx_seg.iloc[-1] - adx_seg.iloc[0])
            ok = ok and (adx_slope >= slope_min)

        return {
            "ok": bool(ok),
            "score": 1.0 if ok else 0.0,
            "notes": {
                "adx": adx_last,
                "plus_di": plus_last,
                "minus_di": minus_last
            }
        }

from .base import register
register(AdxFilter)
