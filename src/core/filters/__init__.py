# src/core/filters/__init__.py
from . import base  # не удалять, тут хранится register/REGISTRY

# ЯВНЫЕ ИМПОРТЫ ВСЕХ ФИЛЬТРОВ, чтобы они регистрировались
from .adx_filter import AdxFilter     # noqa: F401
from .entry_filter import EntryFilter # noqa: F401
from .ofi_filter import OfiFilter     # noqa: F401

__all__ = ["AdxFilter", "EntryFilter", "OfiFilter"]
