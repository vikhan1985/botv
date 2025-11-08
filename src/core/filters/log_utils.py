from __future__ import annotations

from typing import Any

from loguru import logger


def fmt_bps(value: float | None, precision: int = 1) -> str:
    """Format basis points with sign and suffix."""
    if value is None:
        return "n/a"
    return f"{value:+.{precision}f}bps"


def fmt_float(value: float | None, precision: int = 2) -> str:
    """Format float with fixed precision."""
    if value is None:
        return "n/a"
    return f"{value:.{precision}f}"


def log_filter(name: str, symbol: str, ok: bool | None, **fields: Any) -> None:
    """
    Structured logging helper for filter runs.
    ok:
        True  → filter passed
        False → filter rejected
        None  → informational/skip
    Additional keyword arguments are appended as key=value pairs.
    """
    status = "ok" if ok is True else "fail" if ok is False else "skip"

    parts: list[str] = [f"[{name.upper()}]", symbol, status]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={value}")

    logger.info(" ".join(parts))
