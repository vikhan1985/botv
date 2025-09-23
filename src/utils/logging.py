from __future__ import annotations

from loguru import logger
from pathlib import Path
import sys

def setup_logging(loglevel: str = "INFO", log_dir: str = "logs", filename: str = "bot_h15.log") -> None:
    '''
    Initialize loguru logger with stdout + file rotation.
    '''
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stdout, level=loglevel.upper(), format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level:7}</level> | {module}:{function}:{line} - <cyan>{message}</cyan>")
    logger.add(
        Path(log_dir) / filename,
        rotation="10 MB",
        retention="7 days",
        compression="zip",
        level=loglevel.upper(),
        enqueue=True,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:7} | {module}:{function}:{line} - {message}",
    )
