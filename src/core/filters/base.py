from __future__ import annotations
from typing import Dict
from ..contracts import Filter

REGISTRY: Dict[str, Filter] = {}

def register(cls):
    """Класс-фильтр с .name будет зарегистрирован как плагин."""
    inst = cls()
    REGISTRY[inst.name] = inst
    return cls
