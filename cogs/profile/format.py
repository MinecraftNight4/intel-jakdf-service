# cogs/profile/format.py
"""Textos compartidos de /profile: estrellas de dupes y etiquetas de estado."""
from typing import List, Tuple

from .store import LOCKED, MAX_DUPES


def stars(dupes: int) -> str:
    """0 dupes → ☆☆☆☆☆☆ · 3 dupes → ★★★☆☆☆ · 6 dupes → ★★★★★★"""
    dupes = max(0, min(MAX_DUPES, dupes))
    return "✦ " * dupes + "✧ " * (MAX_DUPES - dupes)


def status_label(value: int) -> str:
    if value == LOCKED:
        return "🔒 Not obtained"
    if value == 0:
        return f"{stars(0)} First pull"
    return f"{stars(value)} +{value} dupe{'s' if value > 1 else ''}"


# (valor, etiqueta) en el orden en que se ofrecen: bloqueado, sin dupes, +1 … +6
STATUS_OPTIONS: List[Tuple[int, str]] = [(v, status_label(v)) for v in [LOCKED, *range(0, MAX_DUPES + 1)]]
