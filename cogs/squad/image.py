# cogs/squad/image.py
"""Imagen de /squad share con Typst: Python manda datos, ``share_template.typ`` decide como se ve.

Requiere ``pip install typst``. Archivos que lee:
  ``sys_save/profile/characters/{uuid}.webp``   icono de cada personaje
  ``sys_save/profile/icon/duo.png``            icono entre 1-2 y 3-4 de cada fila
  ``sys_save/profile/icon/and.png``            icono entre 2-3 de cada fila
  ``sys_save/profile/bungee-regular.ttf``      fuente del titulo
  ``sys_save/profile/gothic-regular.ttf``      fuente de descripcion y nombres (mayusculas y minusculas)
"""
import colorsys
import hashlib
import json
import os
import struct
from functools import lru_cache
from typing import Dict, List, Optional

from .codec import Build
from .render import EMPTY_NAME

TEMPLATE = os.path.join(os.path.dirname(__file__), "share_template.typ")
FONT_DIR = "sys_save/profile"
TITLE_FONT = os.path.join(FONT_DIR, "bungee-regular.ttf")
BODY_FONT = os.path.join(FONT_DIR, "gothic-regular.ttf")
SEP_DIR = os.path.join(FONT_DIR, "icon")
ICON_DIR = "sys_save/profile/characters"
ICON_EXT = ".png"
PPI = 144                       # 2x: nitido al verse en Discord


def _rooted(path: str) -> Optional[str]:
    """Ruta relativa a la raiz del proyecto con ``/`` inicial (como la quiere Typst), o None si no existe."""
    return "/" + os.path.relpath(path).replace(os.sep, "/") if os.path.isfile(path) else None


def icon_path(uuid: int) -> Optional[str]:
    return _rooted(os.path.join(ICON_DIR, f"{uuid}{ICON_EXT}"))


@lru_cache(maxsize=256)
def prefix_color(prefix: str) -> str:
    """Color del prefijo, siempre el mismo para el mismo texto (hash). Claro, para leerse sobre gris oscuro."""
    digest = hashlib.md5(prefix.strip().lower().encode("utf-8")).hexdigest()
    hue = int(digest[0:4], 16) % 360
    sat = 0.55 + (int(digest[4:6], 16) % 30) / 100.0
    light = 0.64 + (int(digest[6:8], 16) % 14) / 100.0
    r, g, b = (int(c * 255) for c in colorsys.hls_to_rgb(hue / 360.0, light, sat))
    return f"#{r:02x}{g:02x}{b:02x}"


@lru_cache(maxsize=8)
def font_family(path: str, default: str = "DejaVu Sans") -> str:
    """Nombre de familia de un .ttf/.otf (Typst busca la fuente por familia, no por nombre de archivo)."""
    try:
        with open(path, "rb") as fh:
            blob = fh.read(1 << 20)
        count = struct.unpack(">H", blob[4:6])[0]
        for i in range(count):
            tag, _, offset, _ = struct.unpack(">4sIII", blob[12 + 16 * i:28 + 16 * i])
            if tag != b"name":
                continue
            n, base = struct.unpack(">HH", blob[offset + 2:offset + 6])
            found: Dict[int, str] = {}
            for j in range(n):
                plat, _, _, name_id, length, off = struct.unpack(">6H", blob[offset + 6 + 12 * j:offset + 18 + 12 * j])
                if name_id in (1, 16) and plat in (0, 1, 3):
                    raw = blob[offset + base + off:offset + base + off + length]
                    text = raw.decode("utf-16-be" if plat in (0, 3) else "mac_roman", "ignore").strip()
                    if text and (name_id not in found or plat == 3):
                        found[name_id] = text
            return found.get(16) or found.get(1) or default
    except Exception:
        pass
    return default


def _cell(slot: int, uuid: int, by_uuid: Dict[int, dict]) -> dict:
    char = by_uuid.get(uuid) if uuid else None
    if char:
        return {"slot": slot, "image": icon_path(uuid), "prefix": char["prev_name"], "name": char["full_name"],
                "color": prefix_color(char["prev_name"])}
    return {"slot": slot, "image": None, "prefix": "", "name": EMPTY_NAME if not uuid else f"Unknown #{uuid}",
            "color": "#ffffff"}


def build_data(build: Build, by_uuid: Dict[int, dict], creator: str, account: Optional[str]) -> dict:
    """Lo unico que ve la plantilla. ``creator``/``account``: nombres de usuario (sin ``@``)."""
    title = f"BUILD MADE BY @{creator}"
    if build.account_id:
        title += f" - @{account or build.account_id} ACCOUNT"
    cells: List[dict] = [_cell(i + 1, u, by_uuid) for i, u in enumerate(build.slots)]
    return {
        "title": title, "description": build.description or None, "cells": cells,
        "fonts": {"title": font_family(TITLE_FONT), "body": font_family(BODY_FONT)},
        "sep": {"duo": _rooted(os.path.join(SEP_DIR, "duo.png")), "amp": _rooted(os.path.join(SEP_DIR, "and.png"))},
    }


def render_png(data: dict) -> bytes:
    """Compila la plantilla. Bloquea: llamarla con ``asyncio.to_thread``."""
    import typst                                  # import tardio: el resto del cog no lo necesita
    return typst.compile(
        TEMPLATE, format="png", ppi=PPI, root=".",
        font_paths=[FONT_DIR], sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
    )
