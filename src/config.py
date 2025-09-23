
from __future__ import annotations
from pydantic import BaseModel
from dotenv import load_dotenv
import os, yaml

# Загружаем .env, чтобы ENV мог перекрыть YAML далее
load_dotenv()

class Settings(BaseModel):
    # --- Биржа / окружение ---
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_SECRET: str = ""
    TESTNET: bool = False
    TZ: str = "Asia/Almaty"
    MIN_PASSED: int = 6  # минимальное число пройденных фильтров для отправки сигнала
    TAKER_FEE_BPS: float = 0.0  # комиссия тейкер, бпс за сделку (открытие/закрытие учитываются оба)
    SLIPPAGE_BPS: float = 0.0  # ожидаемое проскальзывание в бпс на вход+выход суммарно

    # --- Список инструментов ---
    SYMBOLS: list[str] = []

    # --- Таймфреймы ---
    BASE_TIMEFRAME: str = "1h"
    TREND_TF_FAST: str = "15m"
    TREND_TF_SLOW: str = "4h"

    # --- TP/SL и RR ---
    TP_MODE: str = "R_MULTI"
    TP1_R_MULT: float = 1.8
    TP2_R_MULT: float = 2.5
    TP1_PCT: float = 1.0
    TP2_PCT: float = 1.9
    SL_PCT: float = 0.8

    MIN_RR1: float = 1.2                 # главный порог RR для допуска сигнала
    MIN_RR1_RELAX_DELTA: float = 0.15    # если где-то используется адаптивный RR

    # «плавающие» уровни для раскраски силы RR
    RR1_WEAK: float = 1.2
    RR1_MEDIUM: float = 1.6
    RR1_STRONG: float = 1.8
    RR_EPS: float = 1e-6
    LOG_RR_BELOW_MIN: bool = True

    # --- Фильтры/пороги ---
    ATR_15M_MIN_PCT: float = 0.80
    ATR_1H_MIN_PCT: float = 1.40
    EMA_FAST: int = 21
    EMA_MID: int = 50
    EMA_SLOW: int = 200
    RSI_PERIOD: int = 14
    RSI_BUY_LVL: float = 52.0
    RSI_SELL_LVL: float = 48.0
    VWAP_ANCHOR: str = "UTC00"
    OFI_WINDOW_SEC: int = 600
    OFI_THRESHOLD: float = 0.10
    OI_MIN_CHANGE_PCT_15M: float = 0.50

    MAX_SPREAD_BPS: float = 5.0
    DEPTH_BPS: float = 10.0
    MIN_DEPTH_USDT: float = 100000.0

    ADX_PERIOD: int = 14
    ADX_H1_MIN: float = 22.0
    ADX_REQUIRE_DIRECTION: bool = True

    REQUIRE_CONFIRM_ON_CLOSE: bool = False
    INTRABAR_OFI_TRIGGER: bool = True
    DAILY_MAX_LOSS_USDT: float = 100.0
    ACCOUNT_RISK_PER_TRADE_USDT: float = 10.0
    MAX_CONCURRENT_POSITIONS: int = 3
    LEVERAGE: int = 5
    COOLDOWN_MIN: int = 20
    ENTRY_RANGE_BPS: int = 8

    # --- S/R & SRT ---
    REQUIRE_SRT: bool = True
    SR_CONFIRM_BPS: int = 1
    SR_NEAR_BPS: int = 18
    SR_NEAR_NEEDS: list[str] = ["vwap","adx"]
    SRT_MODE: str = "RELAX"
    SRT_FALLBACK_BPS: int = 18

    # --- Подтверждения входа ---
    ENTRY_CONFIRM: bool = False
    ENTRY_TFS: list[str] = ["5m","15m"]
    ENTRY_BARS: int = 2
    ENTRY_REQUIRE_ANY: bool = True

    # --- Планировщик / защита от банов ---
    SCHED_MAX_PARALLEL: int = 3
    SCAN_JITTER_MS: int = 500
    SYMBOL_COOLDOWN_SEC: int = 1200

    # --- Telegram ---
    TELEGRAM_ENABLED: bool = True
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""

    # --- Отчёты/статистика (опц.) ---
    REPORTS_ENABLED: bool = False
    REPORT_TZ: str = "Asia/Almaty"
    REPORT_TIME_LOCAL: str = "20:00"
    STATS_DIR: str = "stats"
    EVAL_LOOKAHEAD_HOURS: int = 48

def _apply_yaml(s: Settings, config_path: str | None) -> None:
    if config_path and os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            y = yaml.safe_load(f) or {}
            for k, v in y.items():
                if hasattr(s, k):
                    setattr(s, k, v)

def _apply_env_overrides(s: Settings) -> None:
    """ENV перекрывает ЛЮБОЕ поле Settings (приведение типов автоматическое)."""
    for k in list(s.__dict__.keys()):
        if k in os.environ and os.environ[k] != "":
            val = os.environ[k]
            cur = getattr(s, k)
            try:
                if isinstance(cur, bool):
                    setattr(s, k, str(val).lower() in ("1","true","yes","on","y"))
                elif isinstance(cur, int):
                    setattr(s, k, int(val))
                elif isinstance(cur, float):
                    setattr(s, k, float(val))
                elif isinstance(cur, list):
                    parts = [p.strip() for p in str(val).replace(",", " ").split() if p.strip()]
                    setattr(s, k, parts)
                else:
                    setattr(s, k, str(val))
            except Exception:
                pass  # если не удалось привести — оставляем текущее

def load_settings(config_path: str | None = None) -> "Settings":
    s = Settings()
    _apply_yaml(s, config_path)     # YAML сначала
    _apply_env_overrides(s)         # ENV перекрывает YAML
    return s
