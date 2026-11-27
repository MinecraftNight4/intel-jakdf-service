# cogs/calendar/gacha_helpers.py
"""Imagen de gachas con Typst: Python manda datos, ``gacha.typ`` decide como se ve.

Requiere ``pip install typst`` (Typst 0.13 o superior) y la fuente en ``sys_save/calendar``.
"""
import colorsys
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import requests
import typst

from ..helpers import now_as_unix
from .code import GACHA_IMAGE_PATH, TYPE_LABELS, timesystem_countdown

TEMPLATE = os.path.join(os.path.dirname(__file__), "item_gachas/template.typ")
FONT_DIR = os.path.dirname(GACHA_IMAGE_PATH)      # sys_save/calendar (bungee-regular.ttf)
LOGO_DIR = os.path.join(FONT_DIR, "logos")
COLS, CARD_W, GAP, PAD = 3, 340, 10, 12
PPI = 144                                         # 2x: texto nitido al verse en Discord
DISCLAIMER = (
    "[Akatsuki Games Inc], [Akatsuki], [Production I.G], and [Tōhō] are not affiliated "
    "with this project and are the owners of the attached elements."
)

TYPE_COLORS = {
    "PAID-ONLY": "#dc3232",
    "LIMITED": "#ff961e",
    "STANDARD": "#3296dc",
    "EVENT": "#50c878",
}
_TIMER_GACHA, _TIMER_EVENT, _TIMER_SHOP = "#aad2ff", "#96ffb4", "#ffbe82"


# ------------------------------------------------------------
# Datos
# ------------------------------------------------------------
@lru_cache(maxsize=256)
def _color_from_key(key: str) -> str:
    """Mismo prefijo → mismo color. No hay tabla que mantener."""
    digest = hashlib.md5(key.strip().lower().encode("utf-8")).hexdigest()
    hue = int(digest[0:4], 16) % 360
    sat = 0.55 + (int(digest[4:6], 16) % 30) / 100.0
    light = 0.42 + (int(digest[6:8], 16) % 18) / 100.0
    r, g, b = (int(c * 255) for c in colorsys.hls_to_rgb(hue / 360.0, light, sat))
    return f"#{r:02x}{g:02x}{b:02x}"


def _char(raw: str) -> Dict[str, Any]:
    """``[Prefijo] Nombre`` → prefijo, nombre y color (del prefijo)."""
    match = re.match(r"^(\[[^\]]+\])\s*(.*)$", (raw or "").strip())
    prefix = match.group(1).strip() if match else None
    name = (match.group(2).strip() if match else (raw or "").strip()) or prefix or ""
    return {"prefix": prefix, "name": name, "color": _color_from_key(prefix or name)}


def _timers(banner: Dict[str, Any], now: int) -> List[Dict[str, Any]]:
    pull = timesystem_countdown(banner["pull_ends"], now)
    kind = banner["banner_type"]
    if kind == "PAID-ONLY":
        pairs = [("Gacha", pull, _TIMER_GACHA)]
    elif kind == "EVENT":
        pairs = [("Event", timesystem_countdown(banner.get("play_ends"), now), _TIMER_EVENT),
                 ("Gacha", pull, _TIMER_GACHA)]
    else:
        pairs = [("Banner", pull, _TIMER_GACHA),
                 ("Exchange", timesystem_countdown(banner.get("sell_ends"), now), _TIMER_SHOP)]
    return [{"label": lab, "value": val, "color": color, "expired": val in ("OFFLINE!", "DISABLED!")}
            for lab, val, color in pairs]


# ------------------------------------------------------------
# Logos: cache en disco (Typst lee archivos); no se vuelven a bajar entre ciclos ni reinicios
# ------------------------------------------------------------
def _logo_file(url: str) -> str:
    return os.path.join(LOGO_DIR, hashlib.md5(url.encode()).hexdigest() + ".img")


def _download_logo(url: str) -> None:
    path = _logo_file(url)
    if os.path.exists(path):
        return
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200 and response.content:
            with open(path, "wb") as fh:
                fh.write(response.content)
    except Exception:
        pass


def _prepare_logos(banners: List[Dict[str, Any]]) -> Dict[str, str]:
    """Descarga en paralelo los logos que falten, borra los que ya no se usan y
    devuelve ``{url: ruta}`` (relativa a la raiz) de los que existen."""
    os.makedirs(LOGO_DIR, exist_ok=True)
    urls = {b["banner_logo"] for b in banners if b.get("banner_logo")}
    keep = {os.path.basename(_logo_file(u)) for u in urls}
    for name in os.listdir(LOGO_DIR):
        if name not in keep:
            try:
                os.remove(os.path.join(LOGO_DIR, name))
            except OSError:
                pass
    if urls:
        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            list(pool.map(_download_logo, urls))
    return {u: "/" + os.path.relpath(_logo_file(u)).replace(os.sep, "/")
            for u in urls if os.path.exists(_logo_file(u))}


# ------------------------------------------------------------
# Imagen
# ------------------------------------------------------------
def create_gacha_banner_image(active_banners: List[Dict[str, Any]], relative: bool = False,
                              output: str = GACHA_IMAGE_PATH) -> Optional[str]:
    """PNG de los banners activos (``relative`` se acepta por compatibilidad y no cambia nada)."""
    if not active_banners:
        return None
    now = now_as_unix()
    logos = _prepare_logos(active_banners)
    cols = min(COLS, len(active_banners))
    data = {
        "cols": cols,
        "width": PAD * 2 + cols * CARD_W + (cols - 1) * GAP,
        "disclaimer": DISCLAIMER,
        "banners": [{
            "name": b["banner_name"],
            "kind": TYPE_LABELS.get(b["banner_type"], b["banner_type"]),
            "badge": TYPE_COLORS.get(b["banner_type"], "#646464"),
            "logo": logos.get(b.get("banner_logo")),
            "timers": _timers(b, now),
            "weapons": b.get("pull_gear") or [],
            "chars": [_char(u) for u in b.get("pull_unit") or []],
        } for b in active_banners],
    }
    os.makedirs(os.path.dirname(output), exist_ok=True)
    tmp = output + ".tmp.png"
    typst.compile(
        TEMPLATE, output=tmp, format="png", ppi=PPI, root=".",
        font_paths=[FONT_DIR], sys_inputs={"data": json.dumps(data, ensure_ascii=False)},
    )
    os.replace(tmp, output)   # atomico: nunca se lee un PNG a medio escribir
    return output
