# cogs/calendar/item_gachas.py
"""Banners de gacha activos: filtrado de noticias y panel de Discord.

La imagen la genera ``gacha_helpers.py`` en ``sys_save/calendar/gacha.png``; el panel la adjunta.
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from discord import File, ui

from .helpers import NEWS_FILE, fetchjson, format_time_view, now_as_unix
from .base import add_navigation_buttons

JST = ZoneInfo("Asia/Tokyo")
GACHA_IMAGE_PATH = "sys_save/calendar/gacha.png"
GACHA_IMAGE_NAME = "gacha.png"

# STANDARD se muestra como NO-LIMITED a propósito.
TYPE_LABELS = {
    "PAID-ONLY": "PAID-ONLY",
    "LIMITED": "LIMITED",
    "STANDARD": "NO-LIMITED",
    "EVENT": "EVENT",
}

# Orden importa: cada frase se borra sobre el resultado de la anterior.
_NAME_NOISE = (
    "PAID-ONLY ★5 ",
    "PAID-ONLY ",
    "[LIMITED] ",
    " PICKUP",
    " GACHA",
    " RERUN",
    " NOW AVAILABLE!",
    "ANNIVERSARY ",
    " EVENT",
)


# ============================================================
# TIEMPO
# ============================================================
def timesystem_timezone(ts: int) -> str:
    """Día JST ``YYYY-MM-DD``. Sirve para agrupar lo que termina el mismo día."""
    return datetime.fromtimestamp(ts, tz=JST).strftime("%Y-%m-%d")


def timesystem_countdown(end: Optional[int], now: int) -> str:
    if end is None:
        return "??????"
    if end <= now:
        return "OFFLINE!"
    left = end - now
    days, rem = divmod(left, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}d {hours}h {minutes}m"


# ============================================================
# TEXTO DE LA NOTICIA
# ============================================================
def textfetch_listed_type(name: str, meta: dict) -> str:
    name_up = name.upper()
    if "PAID-ONLY" in name_up or "PAID ONLY" in name_up:
        return "PAID-ONLY"
    if meta.get("event"):
        return "EVENT"
    if "[LIMITED]" in name_up or "LIMITED" in name_up:
        return "LIMITED"
    return "STANDARD"

def _still_active(kind: str, pull: Optional[int], play: Optional[int], sell: Optional[int], now: int) -> bool:
    if not pull:
        return False
    if kind == "PAID-ONLY":
        return pull > now
    if kind == "EVENT":
        return bool(play and play > now) or pull > now
    return pull > now or (sell is not None and sell > now)

def bannerfetch_index(art: dict, now: int) -> List[Dict[str, Any]]:
    meta = art.get("metadata")
    if not isinstance(meta, dict):
        return []

    pull = meta.get("banner")
    play = meta.get("event")
    sell = meta.get("store")
    raw_name = art.get("article_name") or ""
    featured_type = textfetch_listed_type(raw_name, meta)

    if not _still_active(featured_type, pull, play, sell, now):
        return []

    return [{
        "banner_name": textfetch_clear_name(raw_name.upper()),
        "banner_type": featured_type,
        "banner_logo": art.get("article_logo"),
        "pull_unit": (meta.get("unit") or [])[:8],
        "pull_gear": (meta.get("gear") or [])[:8],
        "pull_ends": pull,
        "sell_ends": sell,
        "play_ends": play,
    }]

def textfetch_clear_name(name: str) -> str:
    for noise in _NAME_NOISE:
        name = name.replace(noise, "")
    return name.strip()

def bannerfetch_list() -> List[Dict[str, Any]]:
    articles = fetchjson(NEWS_FILE, {})
    now = now_as_unix()
    active: List[Dict[str, Any]] = []
    for article in articles.values():
        if (article.get("article_type") or "").lower() != "gacha":
            continue
        active.extend(article["metadata"])
    active.sort(key=lambda banner: banner["pull_ends"])
    return active


# ============================================================
# ADJUNTO
# ============================================================
def get_gacha_attachment() -> Optional[File]:
    if os.path.exists(GACHA_IMAGE_PATH):
        return File(GACHA_IMAGE_PATH, filename=GACHA_IMAGE_NAME)
    return None


# ============================================================
# PANEL
# ============================================================
def _soonest_same_day(banners: List[Dict[str, Any]], field: str) -> Tuple[int, List[Dict[str, Any]]]:
    closest = min(timesystem_timezone(banner[field]) for banner in banners)
    same_day = [banner for banner in banners if timesystem_timezone(banner[field]) == closest]
    return min(banner[field] for banner in same_day), same_day


def _departing_header(emoji: str, label: str, ts: int, relative: bool) -> str:
    when = format_time_view(ts, relative, "f")
    on = "" if relative else "on "
    return f"- {emoji} __{label} departing {on}{when}__"


def _named_banner_lines(banners: List[Dict[str, Any]]) -> List[str]:
    lines: List[str] = []
    seen = set()
    for banner in banners:
        name = banner["banner_name"]
        if name in seen:
            continue
        seen.add(name)
        tag = TYPE_LABELS.get(banner.get("banner_type", ""), banner.get("banner_type", ""))
        lines.append(f"  - `[{tag}] {name}`")
    return lines


def _exchange_lines(banners: List[Dict[str, Any]]) -> List[str]:
    chars: List[str] = []
    weapons: List[str] = []
    for banner in banners:
        for unit in banner.get("pull_unit", []):
            if unit not in chars:
                chars.append(unit)
        for weapon in banner.get("pull_gear", []):
            if weapon not in weapons:
                weapons.append(weapon)
    return [f"  - `🪪 {unit}`" for unit in chars] + [f"  - `🔫 {weapon}`" for weapon in weapons]


def panelbuilder_gachas(relative: bool = False, banners: Optional[List[Dict[str, Any]]] = None) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x8E24AA)
    now = now_as_unix()
    active = banners if banners is not None else bannerfetch_list()

    try:
        generated = int(os.path.getmtime(GACHA_IMAGE_PATH))
        stamp = f"The attachment was generated <t:{generated}:R>"
    except OSError:
        stamp = "The attachment will be generated on the next scheduled update"
    container.add_item(ui.TextDisplay(f"## __AVAILABLE GACHAS__\n-# 🖼️ {stamp}"))

    if not active:
        container.add_item(ui.TextDisplay("*No active gacha banners found right now.*"))
    else:
        # Sin imagen todavia (primer schedule pendiente) no se referencia el adjunto.
        if os.path.exists(GACHA_IMAGE_PATH):
            gallery = ui.MediaGallery()
            gallery.add_item(media=f"attachment://{GACHA_IMAGE_NAME}")
            container.add_item(gallery)
            container.add_item(ui.Separator())

        def leaving(field: str, kinds: Optional[Tuple[str, ...]] = None) -> List[Dict[str, Any]]:
            return [
                b for b in active
                if (kinds is None or b["banner_type"] in kinds) and (b.get(field) or 0) > now
            ]

        sections = (
            ("🎪", "Events", "play_ends", ("EVENT",), _named_banner_lines),
            ("🎫", "Gachas", "pull_ends", None, _named_banner_lines),
            ("🏪", "Exchange", "sell_ends", ("LIMITED", "STANDARD"), _exchange_lines),
        )
        lines: List[str] = []
        for emoji, label, field, kinds, render in sections:
            group = leaving(field, kinds)
            if group:
                ts, same = _soonest_same_day(group, field)
                lines += [_departing_header(emoji, label, ts, relative), *render(same), ""]
        if lines:
            container.add_item(ui.TextDisplay("\n".join(lines).strip()))

    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="gachas", relative=relative)
    view.add_item(container)
    return view
