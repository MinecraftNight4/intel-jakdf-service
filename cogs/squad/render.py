# cogs/squad/render.py
"""Textos de una build, compartidos por el constructor y por /squad share (sin discord)."""
from typing import Dict, List, Optional

EMPTY_ICON = "⬛"
EMPTY_NAME = "—"
LINK_ICON = "<:placeholder_1:1574529130559447131>"      # une los 2 iconos de cada par
PLUS_ICON = "<:placeholder_2:1574529140080775339>"      # une los 2 pares
_KEYCAPS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]


def unit_name(char: Optional[dict], uuid: int = 0) -> str:
    """``Nombre [Tag]``; vacio o desconocido tienen su propio texto."""
    if not uuid:
        return EMPTY_NAME
    if char is None:
        return f"❔ #{uuid}"
    return f"{char['full_name']} {char['prev_name']}".strip()


def unit_icon(char: Optional[dict], uuid: int = 0) -> str:
    if not uuid:
        return EMPTY_ICON
    return char["icon"] if char else "❔"


def _rows(slots: List[int]) -> List[List[int]]:
    return [slots[i:i + 4] for i in range(0, len(slots), 4)]


def icons(slots: List[int], by_uuid: Dict[int, dict], big: bool = True) -> str:
    """``A∞B ＋ C∞D`` (4 casillas) o 4 de esas lineas numeradas (16 casillas).

    ``big``: con ``# `` delante (titulo grande). Sin el, un texto solo con emojis ya se ve
    en tamaño "jumbo" (por eso /squad share lo manda en su propio bloque de texto).
    """
    mark = "# " if big else ""
    lines = []
    for row in _rows(slots):
        a, b, c, d = (unit_icon(by_uuid.get(u), u) for u in row)
        lines.append(f"{a}{LINK_ICON}{b}{PLUS_ICON}{c}{LINK_ICON}{d}")
    if len(slots) == 4:
        return mark + lines[0]
    return "\n".join(f"{mark}{_KEYCAPS[i]} {line}" for i, line in enumerate(lines))


def tagged_name(char: Optional[dict], uuid: int = 0) -> str:
    """``[Prefijo] Nombre`` (el prefijo va primero)."""
    if not uuid:
        return EMPTY_NAME
    if char is None:
        return f"❔ #{uuid}"
    return f"{char['prev_name']} {char['full_name']}".strip()


def slot_list(slots: List[int], by_uuid: Dict[int, dict]) -> str:
    """Una linea pequeña por casilla: ``-# 01. [Prefijo] Nombre``."""
    return "\n".join(f"-# {i + 1:02d}. {tagged_name(by_uuid.get(u), u)}" for i, u in enumerate(slots))


def names(slots: List[int], by_uuid: Dict[int, dict]) -> str:
    """``A [x], B [y], ...`` (4 casillas) o ``1: A [x], B [y], ...`` por fila (16 casillas)."""
    lines = [", ".join(unit_name(by_uuid.get(u), u) for u in row) for row in _rows(slots)]
    if len(slots) == 4:
        return lines[0]
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))


