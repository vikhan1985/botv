# bot_h15 — Binance USDT-M Futures H15 Strategy Bot

Production-ready async Python bot for Binance USDT-M (perpetuals) that:
- Scans symbols on 15m with confirmations on 5m/1h
- Enters trades only if **mandatory** filters are green and total **≥6/8**
- TP1 = +1.0% (move SL to BE after TP1), TP2 = +1.9% (1.8–2.0% allowed), SL = 0.6–1.0% (0.8% default)
- Prefers maker (postOnly) entries; uses reduceOnly exits
- Dry-run & Testnet support
- Robust logging with rotation, Windows compatible, no TA-Lib (indicators implemented by numpy/pandas)

## Install (Windows PowerShell)

```powershell
# 1) Create & activate venv
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) Install requirements
pip install -r requirements.txt

# 3) Copy .env.example -> .env and fill keys
copy .env.example .env
notepad .env
notepad config.yaml  # optional overrides
```

## Run (dry-run)

```powershell
# Scan BTC/ETH/SOL in dry-run with DEBUG logs
python -m src.main --dry-run --symbols BTCUSDT,ETHUSDT,SOLUSDT --loglevel DEBUG
```

## Run (testnet)

```powershell
python -m src.main --testnet --symbols BTCUSDT,ETHUSDT --loglevel INFO
```

## One-off diagnostic scan

```powershell
python -m src.debug.h15_scan --symbols BTCUSDT,ETHUSDT,SOLUSDT --loglevel DEBUG
```

## What the 8 filters mean
Mandatory (must be green):
1. Liquidity/Spread — spread ≤ `MAX_SPREAD_BPS` and depth in ±`DEPTH_BPS` ≥ `MIN_DEPTH_USDT`
2. ATR/Volatility — ATR(14, 15m)/Price ≥ `ATR_15M_MIN_PCT` and ATR(14, 1h)/Price ≥ `ATR_1H_MIN_PCT`
3. Trend (HTF+LTF+RSI) — Long: Close_1h>EMA55_1h, EMA21_15m>EMA50_15m, Close_15m>EMA200_15m, RSI≥`RSI_BUY_LVL` (mirror for short)

Optional (need to reach ≥6/8 total with the 3 mandatory above):
4. VWAP — price stable 45–90m over/under day VWAP or reclaim+hold
5. ΔOI — ≥ +`OI_MIN_CHANGE_PCT_15M` for long (≤ − for short) over 15–30m
6. OFI/CVD — OFI≥`OFI_THRESHOLD` (≤ − for short) with matching CVD; no spread blowout
7. SR/Structure — breakout of last 8–12 H15 range or strong level retest/hold
8. ADX (1h) — ADX(14,1h) ≥ `ADX_H1_MIN`; if `ADX_REQUIRE_DIRECTION`, +DI>−DI for long (mirror for short)

## Safety
- Keys are loaded from `.env` (never commit them).
- On connectivity issues, bot fails safe (close-only if needed).
- `DAILY_MAX_LOSS_USDT` and cooldowns enforced.

## Logs
- File: `logs/bot_h15.log` (rotated)
- Tags: `[H15] [SIG] [TRIG] [EXEC] [RISK] [SIZE] [LIQ]`

## Minimal tests
Run:
```powershell
pytest -q
```

## Example log lines
```
2025-08-16 10:00:01 | INFO    | src.signals.detector_h15:evaluate_symbol_h15:310 - [H15] SOLUSDT [SIG] trend=Y atr=Y vwap=Y oi=Y ofi=N sr=Y adx=Y | passed=6/8
2025-08-16 10:00:02 | INFO    | src.scheduler_continuous:_maybe_trigger:185 - [H15] SOLUSDT [TRIG] Eligible LONG | RR=1.23 | entry=192.35 sl=190.82 tp1=194.27 tp2=196.99
2025-08-16 10:00:03 | INFO    | src.execution.orders:_place_entry:121 - [H15] SOLUSDT [EXEC] Enter LONG maker @ 192.36 | size=12.45 | reduceOnly targets placed
2025-08-16 10:00:10 | WARNING | src.risk.rules:record_pnl:18 - [H15] [RISK] DailyPnL=-102.00 USDT → close-only
```


## Telegram уведомления о сигналах

Добавь в `.env`:
```
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789     # свой user/chat id
ENTRY_RANGE_BPS=10             # диапазон входа ±10 б.п. вокруг mid
```

Формат сообщения:
```
🚨 Сигнал: ETC/USDT:USDT
🕒 Время: 2025-08-16 17:43:04 (Asia/Almaty)

➡️ Направление: 🔴 SHORT

🎯 Вход: 22.277 — 22.321 (mid 22.299)
🛑 Stop Loss: 22.522 (-1.00%)
🥇 TP1: 21.965 (+1.50%)
🥈 TP2: 21.853 (+2.00%)
📈 Фильтры пройдены: 100.0%
```
Сообщения отправляются при появлении **eligible** сигнала (≥6/8 с выполнением обязательных фильтров). Дедупликация: не чаще чем раз в 60 сек на символ.
