# cogs/calendar/item_gachas.py
"""Banners de gacha activos: filtrado de noticias y panel de Discord.

La imagen la genera ``gacha_typst.py`` en ``sys_save/calendar/gacha.png``; el panel la adjunta.
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
def textfetch_listed_unit(text: str) -> List[str]:
    """Personajes con forma ``[Rol] Nombre``, hasta 8."""
    found: List[str] = []
    pattern = r"(\[[^\]]+\]\s*[A-Za-z0-9\s\-']+?)(?:\s*\(Optimal|\s*$|\n)"
    for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
        name = re.sub(r"\s+", " ", match.group(1).strip())
        if 5 < len(name) < 80 and name not in found:
            found.append(name)
    return found[:8]


def textfetch_listed_gear(text: str) -> List[str]:
    """Armas con prefijo de tipo (``AR-``, ``GS-``, …), hasta 8."""
    found: List[str] = []
    pattern = r"((?:HM|SH|AR|GS|Lc|SW|Ax|RF|AW|GG|SB|Fs|T|S|PS|HG|SG)[-‐][A-Za-z0-9\- ]+?)(?=\s*[\|\(\[]|$|\n)"
    for match in re.finditer(pattern, text):
        name = match.group(1).strip()
        if name not in found:
            found.append(name)
    return found[:8]


def textfetch_listed_type(name: str, type: str) -> str:
    """PAID-ONLY y LIMITED ganan a la categoría que trae la plantilla."""
    name = name.upper()
    if type == "event":
        return "EVENT"
    if type == "special" or "PAID-ONLY" in name or "PAID ONLY" in name:
        return "PAID-ONLY"
    if "[LIMITED]" in name or "LIMITED" in name:
        return "LIMITED"
    return "STANDARD"


def textfetch_listed_times(text: str) -> List[int]:
    """Timestamps únicos de rangos ``<t:a> - <t:b>``, ordenados."""
    if not text:
        return []
    seen = set()
    unique: List[int] = []
    for start_s, end_s in re.findall(r"<t:(\d+)>\s*-\s*<t:(\d+)>", text):
        start, end = int(start_s), int(end_s)
        if start >= end:
            continue
        for ts in (start, end):
            if ts not in seen:
                seen.add(ts)
                unique.append(ts)
    return sorted(unique)


def textfetch_clear_name(name: str) -> str:
    for noise in _NAME_NOISE:
        name = name.replace(noise, "")
    return name.strip()


def _banner_span(
    kind: str,
    post: int,
    pull: int,
    play: Optional[int] = None,
    sell: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "type": kind,
        "time_post": post,
        "time_pull": pull,
        "time_play": play,
        "time_sell": sell,
    }


def article_template(art: dict) -> Optional[Dict[str, Any]]:
    """Clasifica la noticia según cuántos rangos de tiempo trae.

    - 3 marcas + tienda  → gacha normal (post, pull, exchange)
    - 3 marcas sin tienda → evento (post, fin de evento, fin de gacha)
    - 2 marcas sin tienda → special / paid (post, pull)
    """
    body = "\n".join(str(item) for item in (art.get("article_item") or [])).lower()
    has_pull = "__availability period__" in body
    has_shop = "exchange period" in body
    stamps = textfetch_listed_times(body)
    if not has_pull or not stamps:
        return None

    if has_shop and len(stamps) == 3:
        post, pull, sell = stamps
        return _banner_span("gacha", post, pull, sell=sell)
    if not has_shop and len(stamps) == 3:
        post, play, pull = stamps
        return _banner_span("event", post, pull, play=play)
    if not has_shop and len(stamps) == 2:
        post, pull = stamps
        return _banner_span("special", post, pull)
    return None


def _still_active(kind: str, pull: int, play: Optional[int], sell: Optional[int], now: int) -> bool:
    if kind == "PAID-ONLY":
        return pull > now
    if kind == "EVENT":
        return bool(play and play > now) or pull > now
    return pull > now or (sell is not None and sell > now)


def bannerfetch_index(art: dict, now: int) -> List[Dict[str, Any]]:
    """0 o 1 banner. Lista para poder hacer ``extend`` en el listado."""
    info = article_template(art)
    if info is None:
        return []

    raw_name = art.get("article_name") or ""
    featured_type = textfetch_listed_type(raw_name, info["type"])
    pull, play, sell = info["time_pull"], info["time_play"], info["time_sell"]
    if not _still_active(featured_type, pull, play, sell, now):
        return []

    full_text = "\n".join(str(part) for part in (art.get("article_item") or []))
    return [{
        "banner_name": textfetch_clear_name(raw_name.upper()),
        "banner_type": featured_type,
        "banner_logo": art.get("article_logo"),
        "pull_unit": textfetch_listed_unit(full_text),
        "pull_gear": textfetch_listed_gear(full_text),
        "pull_ends": pull,
        "sell_ends": sell,
        "play_ends": play,
    }]


def bannerfetch_list() -> List[Dict[str, Any]]:
    articles = fetchjson(NEWS_FILE, {})
    now = now_as_unix()
    active: List[Dict[str, Any]] = []
    for article in articles.values():
        if (article.get("article_type") or "").lower() != "gacha":
            continue
        active.extend(bannerfetch_index(article, now))
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
