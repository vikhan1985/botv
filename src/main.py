from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress

from loguru import logger

# Опционально ускоряем ивент-луп
try:
    import uvloop  # type: ignore
    uvloop.install()
except Exception:
    pass

from .config import load_settings
from .data.binance_client import normalize_symbol
from .utils.logging import setup_logging
from .data.binance_client import get_exchange
from .execution.router import DryRunner, RealRouter
from .scheduler_continuous import Scheduler
from .utils.watchlist import build_watchlist  # авто-подбор пар


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=str, default="config.yaml")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--testnet", action="store_true")
    p.add_argument("--symbols", type=str, default="BTCUSDT,ETHUSDT,SOLUSDT")
    p.add_argument("--loglevel", type=str, default="INFO")
    p.add_argument("--close-only", action="store_true")
    p.add_argument("--scan-interval-ms", type=int, default=60_000)
    # авто-watchlist
    p.add_argument("--auto-watchlist", action="store_true")
    p.add_argument("--watchlist-top", type=int, default=15)
    p.add_argument("--watchlist-refresh-min", type=int, default=1440)
    return p.parse_args()


def _log_cfg_summary(s) -> None:
    try:
        logger.info(
            "CFG | TFs base=%s slow=%s fast=%s | SRT_MODE=%s fallback_bps=%s "
            "confirm_on_close=%s entry_confirm=%s | RR1>=%.2f (relax=%.2f) | "
            "SR: look=%s confirm_bps=%s near_bps=%s near_needs=%s",
            getattr(s, "BASE_TIMEFRAME", None),
            getattr(s, "TREND_TF_SLOW", None),
            getattr(s, "TREND_TF_FAST", None),
            getattr(s, "SRT_MODE", None),
            getattr(s, "SRT_FALLBACK_BPS", 0),
            getattr(s, "REQUIRE_CONFIRM_ON_CLOSE", False),
            getattr(s, "ENTRY_CONFIRM", False),
            float(getattr(s, "MIN_RR1", 0.0) or 0.0),
            float(getattr(s, "MIN_RR1_RELAX_DELTA", 0.0) or 0.0),
            getattr(s, "SWING_LOOKBACK_H15", None),
            getattr(s, "SR_CONFIRM_BPS", 0),
            getattr(s, "SR_NEAR_BPS", 0),
            getattr(s, "SR_NEAR_NEEDS", []),
        )
    except Exception:
        pass


async def amain():
    args = parse_args()
    setup_logging(args.loglevel)

    # Загружаем настройки
    s = load_settings(args.config)
    if args.testnet:
        s.TESTNET = True

    # Разворачиваем список символов из CLI (если не будет авто-watchlist)
    s.SYMBOLS = [x.strip() for x in args.symbols.split(",") if x.strip()]
    # ---- Build watchlist BEFORE starting bot ----
    DEFAULT_CLI = ['BTCUSDT','ETHUSDT','SOLUSDT']
    user_overrode = [x.strip().upper() for x in args.symbols.split(',') if x.strip()]
    user_overrode = (user_overrode != DEFAULT_CLI)
    got_watchlist = False

    def _cfg_get(key, default=None):
        try:
            val = getattr(s, key)
            if val is not None:
                return val
        except Exception:
            pass
        try:
            import os
            if key in os.environ:
                return os.environ[key]
        except Exception:
            pass
        try:
            import yaml
            with open(args.config, 'r', encoding='utf-8') as _f:
                _raw = yaml.safe_load(_f) or {}
            return _raw.get(key, default)
        except Exception:
            return default

    mode = str(_cfg_get('WATCHLIST_MODE', 'classic')).lower()
    logger.info(f"[H15] [WATCHLIST] mode={mode} auto={args.auto_watchlist} user_overrode={user_overrode}")
    if not args.auto_watchlist and not user_overrode:
        if mode == 'static':
            tiers = _cfg_get('WATCHLIST_TIERS', {}) or {}
            use = _cfg_get('WATCHLIST_USE', ['A','B'])
            picked = []
            ALIASES = {
            'MATICUSDT': 'POLUSDT',
            'MATIC/USDT:USDT': 'POL/USDT:USDT',
            }

            for t in use:
                arr = (tiers.get(t) or []) if isinstance(tiers, dict) else []
                for sym in arr:
                    u = str(sym).upper().replace('/USDT:USDT','USDT').replace('/','')
                    u = ALIASES.get(u, u)
                    if u and u not in picked:
                        picked.append(u)
            if picked:
                s.SYMBOLS = picked
                _first12 = s.SYMBOLS[:12]; _more = ' ...' if len(s.SYMBOLS) > 12 else ''
                logger.info(f"[H15] [WATCHLIST] static picked {len(s.SYMBOLS)}; first 12: {_first12}{_more}")
                got_watchlist = True
            else:
                logger.warning('[H15] [WATCHLIST] static empty, will try learned/classic')
        if not got_watchlist and mode == 'learned':
            try:
                from .watchlist_learned import build_learned_watchlist
                top_n = int(_cfg_get('WATCHLIST_TOP', 60) or 60)
                picked_learned = await build_learned_watchlist(ex, s, top_n=top_n)
                if picked_learned:
                    s.SYMBOLS = [p.replace('/USDT:USDT','USDT').replace('/','') for p in picked_learned]
                    _first12 = s.SYMBOLS[:12]; _more = ' ...' if len(s.SYMBOLS) > 12 else ''
                    logger.info(f"[H15] [WATCHLIST] learned picked {len(s.SYMBOLS)}; first 12: {_first12}{_more}")
                    got_watchlist = True
                else:
                    logger.warning('[H15] [WATCHLIST] learned empty, will try classic')
            except Exception as e:
                logger.warning(f"[H15] [WATCHLIST] learned failed: {e}")
        if not got_watchlist:
            try:
                from .universe import build_classic_watchlist
                top_n = int(_cfg_get('WATCHLIST_TOP', 60) or 60)
                picked_classic = await build_classic_watchlist(ex, s, top_n=top_n)
                if picked_classic:
                    s.SYMBOLS = [p.replace('/USDT:USDT','USDT').replace('/','') for p in picked_classic]
                    _first12 = s.SYMBOLS[:12]; _more = ' ...' if len(s.SYMBOLS) > 12 else ''
                    logger.info(f"[H15] [WATCHLIST] classic picked {len(s.SYMBOLS)}; first 12: {_first12}{_more}")
                else:
                    logger.warning('[H15] [WATCHLIST] classic empty; keep provided --symbols')
            except Exception as e:
                logger.warning(f"[H15] [WATCHLIST] classic failed: {e}")
    # Определяем, переопределил ли пользователь список символов через --symbols
    DEFAULT_CLI = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
    user_overrode = [x.strip().upper() for x in args.symbols.split(',') if x.strip()]
    user_overrode = (user_overrode != DEFAULT_CLI)

    # Статический тировый вотчлист из config.yaml (если включён и пользователь не переопределил symbols)
    got_watchlist = False
    try:
        mode = str(getattr(s, 'WATCHLIST_MODE', 'classic')).lower()
    except Exception:
        mode = 'classic'
    if mode == 'static' and (not args.auto_watchlist) and (not user_overrode):
        try:
            tiers = getattr(s, 'WATCHLIST_TIERS', {}) or {}
            use = getattr(s, 'WATCHLIST_USE', ['A','B'])
            picked = []
            for t in use:
                arr = tiers.get(t, []) or []
                for sym in arr:
                    u = str(sym).upper().replace('/USDT:USDT','USDT').replace('/','')
                    if u and u not in picked:
                        picked.append(u)
            if picked:
                s.SYMBOLS = picked
                _first12 = s.SYMBOLS[:12]; _more = ' ...' if len(s.SYMBOLS) > 12 else ''
                logger.info(f"[H15] [WATCHLIST] static picked {len(s.SYMBOLS)}; first 12: {_first12}{_more}")
                got_watchlist = True
            else:
                logger.warning('[H15] [WATCHLIST] static empty; keep provided --symbols')
        except Exception as e:
            logger.warning(f"[H15] [WATCHLIST] static failed: {e}")

    # Форсируем dry-run, если нет ключей (бот сможет работать без ключей)
    has_keys = bool(getattr(s, "BINANCE_API_KEY", "") and getattr(s, "BINANCE_API_SECRET", ""))
    if not has_keys and not args.dry_run:
        logger.warning("No Binance API keys found → forcing --dry-run (signals only).")
        args.dry_run = True

    # Инициализируем биржу (async фабрика)
    ex = await get_exchange(s)
    refresh_task = None
    try:
        await ex.load_markets()
        router = DryRunner(ex) if args.dry_run else RealRouter(ex)

        # Авто-подбор пар на старте (если включён)
        if args.auto_watchlist:
            picked = await build_watchlist(ex, s, args.watchlist_top)
            if picked:
                s.SYMBOLS = [m.replace("/USDT:USDT", "USDT").replace("/", "") for m in picked]
                logger.info(f"[H15] [WATCHLIST] overriding symbols with auto-picked: {s.SYMBOLS}")
            else:
                logger.warning("[H15] [WATCHLIST] no candidates found, keep provided --symbols")

        logger.info(
            f"Starting Binance H15 Bot | dry_run={args.dry_run} testnet={s.TESTNET} symbols={s.SYMBOLS}"
        )
        _log_cfg_summary(s)

        # Создаём планировщик ДО фоновых задач
        sched = Scheduler(
            ex,
            router,
            s,
            s.SYMBOLS,
            close_only=args.close_only,
            scan_interval_ms=args.scan_interval_ms,
        )

        # Опционально: поставить плечо для всех символов (тихо игнорировать ошибки)
        try:
            lev = int(getattr(s, "LEVERAGE", 0) or 0)
        except Exception:
            lev = 0
        if lev and s.SYMBOLS:
            for _sym in s.SYMBOLS:
                try:
                    await ex.set_leverage(lev, normalize_symbol(_sym))
                except Exception:
                    pass

        # Фоновый авто-вотчлист
        async def _refresh_loop():
            if not args.auto_watchlist or args.watchlist_refresh_min <= 0:
                return
            interval = max(60, args.watchlist_refresh_min * 60)
            while True:
                try:
                    picked2 = await build_watchlist(ex, s, args.watchlist_top)
                    if picked2:
                        new_list = [m.replace("/USDT:USDT", "USDT").replace("/", "") for m in picked2]
                        sched.symbols = new_list
                        logger.info(f"[H15] [WATCHLIST] refreshed symbols: {new_list}")
                except Exception as e:
                    logger.warning(f"[H15] [WATCHLIST] refresh failed: {e}")
                await asyncio.sleep(interval)

        if args.auto_watchlist and args.watchlist_refresh_min > 0:
            refresh_task = asyncio.create_task(_refresh_loop())

        # Основной цикл
        await sched.run()

    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — shutting down gracefully...")
    finally:
        # Останавливаем фоновый таск авто-watchlist
        if refresh_task:
            refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await refresh_task

        # Закрываем клиент биржи
        try:
            await ex.close()
        except Exception:
            pass


def main():
    asyncio.run(amain())


if __name__ == "__main__":
    main()
