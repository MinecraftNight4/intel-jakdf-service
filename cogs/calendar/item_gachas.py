# cogs/calendar/item_gachas.py
"""Banners de gacha activos: filtrado de noticias, PNG y panel de Discord.

El PNG se guarda en ``sys_save/calendar/gacha.png`` y el panel lo adjunta.
"""
import colorsys
import hashlib
from functools import lru_cache
import io
import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageChops, ImageDraw, ImageFont
from discord import File, ui

from .helpers import NEWS_FILE, fetchjson, format_time_view, now_as_unix
from .base import add_navigation_buttons

JST = ZoneInfo("Asia/Tokyo")
GACHA_IMAGE_PATH = "sys_save/calendar/gacha.png"
GACHA_IMAGE_NAME = "gacha.png"
FONT_PATH = "sys_save/calendar/bungee-regular.ttf"

# Etiquetas visibles. STANDARD se muestra como NO-LIMITED a propósito.
TYPE_COLORS = {
    "PAID-ONLY": (220, 50, 50),
    "LIMITED": (255, 150, 30),
    "STANDARD": (50, 150, 220),
    "EVENT": (80, 200, 120),
}
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

# Lienzo. El ancho de cada tarjeta lo marca el texto, entre estos topes.
COLS = 3
MIN_CARD_W = 340
MAX_CARD_W = 900
PADDING = 12
GAP = 10
HEADER_H = 48
FOOTER_H = 36
BANNER_AREA_H = 118
BANNER_RADIUS = 10
INNER = 12
CHIP_GAP = 5
LIST_GAP = 16

_TIMER_GACHA = (170, 210, 255)
_TIMER_EVENT = (150, 255, 180)
_TIMER_SHOP = (255, 190, 130)
_CHIP_FILL = (48, 50, 64)
_TIMER_FILL = (48, 50, 68)
_WEAPON_BORDER = (110, 115, 140)
_WEAPON_TEXT = (210, 215, 230)


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
# DIBUJO
# ============================================================
def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype(FONT_PATH, size)
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _content_bbox(img: Image.Image, threshold: int = 28) -> Tuple[int, int, int, int]:
    """Recorta barras negras. Cualquier canal por encima del umbral cuenta como contenido."""
    rgb = img.convert("RGB")
    width, height = rgb.size
    r, g, b = (band.point(lambda v: 255 if v > threshold else 0) for band in rgb.split())
    box = ImageChops.lighter(ImageChops.lighter(r, g), b).getbbox()
    if box is None:
        return (0, 0, width, height)
    pad = 2
    return (
        max(0, box[0] - pad),
        max(0, box[1] - pad),
        min(width, box[2] + pad),
        min(height, box[3] + pad),
    )


def _dominant_color(img: Image.Image) -> Tuple[int, int, int]:
    """Tono saturado del logo, para rellenar los laterales en vez de dejarlos negros."""
    try:
        small = img.convert("RGB").resize((80, 80), Image.Resampling.LANCZOS)
        raw = small.tobytes()
        pixels = list(zip(raw[0::3], raw[1::3], raw[2::3]))
        buckets: Dict[Tuple[int, int, int], float] = {}
        for r, g, b in pixels:
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 40 or mn > 235:
                continue
            sat = (mx - mn) / (mx + 1e-6)
            lum = (r + g + b) / 3.0
            if sat < 0.08 and lum < 50:
                continue
            key = (r // 12 * 12, g // 12 * 12, b // 12 * 12)
            weight = 1.0 + sat * 3.0 + (0.5 if 50 < lum < 180 else 0.0)
            buckets[key] = buckets.get(key, 0.0) + weight
        if not buckets:
            n = len(pixels) or 1
            return (
                max(45, sum(p[0] for p in pixels) // n),
                max(45, sum(p[1] for p in pixels) // n),
                max(45, sum(p[2] for p in pixels) // n),
            )
        top = sorted(buckets.items(), key=lambda kv: -kv[1])[:3]
        total = sum(weight for _, weight in top) or 1.0
        r = int(sum(key[0] * weight for key, weight in top) / total)
        g = int(sum(key[1] * weight for key, weight in top) / total)
        b = int(sum(key[2] * weight for key, weight in top) / total)
        return (max(r, 40), max(g, 40), max(b, 40))
    except Exception:
        return (55, 50, 75)


@lru_cache(maxsize=256)
def _color_from_key(key: str) -> Tuple[int, int, int]:
    """Mismo prefijo → mismo color. No hay tabla que mantener."""
    digest = hashlib.md5(key.strip().lower().encode("utf-8")).hexdigest()
    hue = int(digest[0:4], 16) % 360
    sat = 0.55 + (int(digest[4:6], 16) % 30) / 100.0
    light = 0.42 + (int(digest[6:8], 16) % 18) / 100.0
    return tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue / 360.0, light, sat))


def _parse_char_parts(raw: str) -> Tuple[Optional[str], str]:
    """``[Prefijo] Nombre`` → (prefijo con corchetes, nombre)."""
    match = re.match(r"^(\[[^\]]+\])\s*(.*)$", (raw or "").strip())
    if not match:
        return None, (raw or "").strip()
    prefix = match.group(1).strip()
    name = (match.group(2) or "").strip() or prefix
    return prefix, name


def _rounded_mask(width: int, height: int, radius: int) -> Image.Image:
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, width - 1, height - 1], radius=radius, fill=255)
    return mask


def _fit_single_line(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    text = (text or "").replace("\n", " ").strip()
    if not text or _text_width(draw, text, font) <= max_width:
        return text
    ellipsis = "…"
    while text and _text_width(draw, text + ellipsis, font) > max_width:
        text = text[:-1]
    return (text + ellipsis) if text else ellipsis


def _measure_timer_chip(
    draw: ImageDraw.ImageDraw, label: str, value: str, font: ImageFont.ImageFont
) -> Tuple[int, int]:
    pad_x, pad_y = 10, 6
    return _text_width(draw, f"{label}: {value}", font) + pad_x * 2, 14 + pad_y * 2


def _draw_timer_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    value: str,
    label_color: Tuple[int, int, int],
    font: ImageFont.ImageFont,
    max_width: Optional[int] = None,
) -> Tuple[int, int]:
    """Chip de cuenta atrás. El texto no se recorta; solo OFFLINE!/DISABLED! va en rojo."""
    pad_x, pad_y, radius = 10, 6, 6
    label_part = f"{label}: "
    text_full = label_part + value
    chip_w = _text_width(draw, text_full, font) + pad_x * 2
    if max_width is not None and chip_w > max_width:
        pad_x = 4
        chip_w = _text_width(draw, text_full, font) + pad_x * 2
        if chip_w > max_width:
            chip_w = max_width
    chip_h = 14 + pad_y * 2
    draw.rounded_rectangle(
        [x, y, x + chip_w, y + chip_h],
        radius=radius,
        fill=_TIMER_FILL,
        outline=(110, 115, 150),
        width=2,
    )
    label_w = _text_width(draw, label_part, font)
    draw.text((x + pad_x, y + pad_y), label_part, fill=label_color, font=font)
    value_color = (255, 55, 55) if value in ("DISABLED!", "OFFLINE!") else label_color
    draw.text((x + pad_x + label_w, y + pad_y), value, fill=value_color, font=font)
    return chip_w, chip_h


def _draw_item_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    width: int,
    text: str,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
    kind: str = "weapon",
) -> int:
    """Chip de ancho fijo. Personaje: borde y texto del color del prefijo. Arma: gris neutro."""
    pad_x, pad_y, gap = 8, 5, 2
    max_text_w = max(20, width - pad_x * 2)
    prefix, name = _parse_char_parts(text) if kind == "character" else (None, text)
    if kind == "character":
        accent = border = _color_from_key(prefix or name)
    else:
        accent, border = _WEAPON_TEXT, _WEAPON_BORDER

    # (texto ajustado, fuente) por linea: el prefijo del personaje va arriba, mas pequeno.
    lines = [(_fit_single_line(draw, name, font, max_text_w), font)]
    if prefix:
        lines.insert(0, (_fit_single_line(draw, prefix, font_small, max_text_w), font_small))

    line_h = 14 if prefix else 16
    chip_h = pad_y * 2 + line_h * len(lines) + gap * (len(lines) - 1)
    draw.rounded_rectangle([x, y, x + width, y + chip_h], radius=6, fill=_CHIP_FILL, outline=border, width=2)
    ty = y + pad_y
    for line, line_font in lines:
        draw.text((x + (width - _text_width(draw, line, line_font)) // 2, ty), line, fill=accent, font=line_font)
        ty += line_h + gap
    return chip_h


def _chip_content_width(
    measure: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
    kind: str,
) -> int:
    pad = 20
    if kind != "character":
        return _text_width(measure, text, font) + pad
    prefix, name = _parse_char_parts(text)
    if prefix:
        return max(_text_width(measure, prefix, font_small), _text_width(measure, name, font)) + pad
    return _text_width(measure, name or text, font) + pad


def _est_chip_h(item: str, kind: str) -> int:
    if kind == "character" and _parse_char_parts(item)[0]:
        return 38
    return 26


def _load_fonts() -> Dict[str, ImageFont.ImageFont]:
    return {
        "title": _font(20),
        "name": _font(14),
        "small": _font(12),
        "badge": _font(12),
        "chip": _font(11),
        "chip_sm": _font(10),
        "section": _font(11),
        "disclaimer": _font(10),
    }


def _banner_timers(banner: Dict[str, Any], now: int) -> List[Tuple[str, str, Tuple[int, int, int]]]:
    pull = timesystem_countdown(banner["pull_ends"], now)
    kind = banner["banner_type"]
    if kind == "PAID-ONLY":
        return [("Gacha", pull, _TIMER_GACHA)]
    if kind == "EVENT":
        play = timesystem_countdown(banner.get("play_ends"), now)
        return [("Event", play, _TIMER_EVENT), ("Gacha", pull, _TIMER_GACHA)]
    sell = timesystem_countdown(banner.get("sell_ends"), now)
    return [("Banner", pull, _TIMER_GACHA), ("Exchange", sell, _TIMER_SHOP)]


def _plan_canvas(
    banners: List[Dict[str, Any]], fonts: Dict[str, ImageFont.ImageFont]
) -> Tuple[int, List[Dict[str, Any]], List[int], int, int]:
    """Ancho de tarjeta (para que quepa el texto) y alto de cada fila."""
    measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    font_name, font_small = fonts["name"], fonts["small"]
    font_chip, font_chip_sm, font_section = fonts["chip"], fonts["chip_sm"], fonts["section"]

    max_title_w = max_wpn_w = max_char_w = 0
    worst = "99d 99h 99m"
    max_timer_w = 0
    for sample in (f"Banner: {worst}", f"Exchange: {worst}", f"Event: {worst}", f"Gacha: {worst}"):
        max_timer_w = max(max_timer_w, _text_width(measure, sample, font_small) + 24)

    for banner in banners:
        max_title_w = max(max_title_w, _text_width(measure, banner["banner_name"], font_name))
        for weapon in banner.get("pull_gear") or []:
            max_wpn_w = max(max_wpn_w, _chip_content_width(measure, weapon, font_chip, font_chip_sm, "weapon"))
        for unit in banner.get("pull_unit") or []:
            max_char_w = max(max_char_w, _chip_content_width(measure, unit, font_chip, font_chip_sm, "character"))

    section_w = max(
        _text_width(measure, "FEATURED WEAPONS", font_section),
        _text_width(measure, "FEATURED CHARACTERS", font_section),
    )
    col_left = max(max_wpn_w, section_w + 4, max_timer_w, 90)
    col_right = max(max_char_w, section_w + 4, max_timer_w, 90)
    need_cols = INNER * 2 + col_left + col_right + LIST_GAP
    need_title = 90 + 10 + max_title_w + INNER * 2
    card_w = min(MAX_CARD_W, max(MIN_CARD_W, need_cols, need_title))
    name_w = card_w - 110 - INNER

    layouts: List[Dict[str, Any]] = []
    for banner in banners:
        raw_title = (banner["banner_name"] or "").replace("\n", " ").strip()
        title = raw_title if _text_width(measure, raw_title, font_name) <= name_w else _fit_single_line(measure, raw_title, font_name, name_w)
        weapons = banner.get("pull_gear") or []
        chars = banner.get("pull_unit") or []
        weapons_h = sum(_est_chip_h(item, "weapon") + CHIP_GAP for item in weapons) if weapons else 14
        chars_h = sum(_est_chip_h(item, "character") + CHIP_GAP for item in chars) if chars else 14
        list_h = max(weapons_h, chars_h, 14)
        layouts.append({
            "banner": banner,
            "title": title,
            "weapons": weapons,
            "chars": chars,
            "height": BANNER_AREA_H + 10 + 22 + 8 + 30 + 6 + 16 + 4 + list_h + INNER,
        })

    row_heights: List[int] = []
    rows = (len(layouts) + COLS - 1) // COLS
    for row in range(rows):
        chunk = layouts[row * COLS:(row + 1) * COLS]
        row_heights.append(max(card["height"] for card in chunk))

    width = PADDING * 2 + COLS * card_w + (COLS - 1) * GAP
    height = HEADER_H + PADDING + sum(row_heights) + max(0, rows - 1) * GAP + PADDING + FOOTER_H
    return card_w, layouts, row_heights, width, height


_LOGO_CACHE: Dict[str, bytes] = {}


def _fetch_logo(url: str) -> Optional[bytes]:
    """Descarga el logo una sola vez; los siguientes ciclos usan la copia en memoria."""
    cached = _LOGO_CACHE.get(url)
    if cached is not None:
        return cached
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200 and response.content:
            _LOGO_CACHE[url] = response.content
            return response.content
    except Exception:
        pass
    return None


def _prefetch_logos(banners: List[Dict[str, Any]]) -> None:
    """Descarga en paralelo los logos que falten y descarta los que ya no se usan."""
    urls = {b.get("banner_logo") for b in banners if b.get("banner_logo")}
    for stale in [u for u in _LOGO_CACHE if u not in urls]:
        _LOGO_CACHE.pop(stale, None)
    for key in [k for k in _TILE_CACHE if k[0] not in urls]:
        _TILE_CACHE.pop(key, None)
    missing = [u for u in urls if u not in _LOGO_CACHE]
    if missing:
        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as pool:
            list(pool.map(_fetch_logo, missing))


_TILE_CACHE: Dict[Tuple[str, int, int], Image.Image] = {}


def _logo_tile(url: str, area_w: int, area_h: int) -> Optional[Image.Image]:
    """Logo ya recortado, centrado y con esquinas redondeadas. Se arma una vez por tamano."""
    key = (url, area_w, area_h)
    tile = _TILE_CACHE.get(key)
    if tile is not None:
        return tile
    content = _fetch_logo(url)
    if not content:
        return None
    try:
        logo = Image.open(io.BytesIO(content)).convert("RGBA")
        box = _content_bbox(logo, threshold=25)
        if box[2] - box[0] > 10 and box[3] - box[1] > 10:
            logo = logo.crop(box)
        lw, lh = logo.size
        if lw <= 0 or lh <= 0:
            return None
        color = _dominant_color(logo)
        tile = Image.new("RGBA", (area_w, area_h), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rounded_rectangle(
            [0, 0, area_w - 1, area_h - 1], radius=BANNER_RADIUS, fill=(*color, 255)
        )
        scale = min(area_w / lw, area_h / lh)
        resized = logo.resize((max(1, int(lw * scale)), max(1, int(lh * scale))), Image.Resampling.LANCZOS)
        tile.paste(resized, ((area_w - resized.size[0]) // 2, (area_h - resized.size[1]) // 2), resized)
        tile.putalpha(_rounded_mask(area_w, area_h, BANNER_RADIUS))
    except Exception:
        return None
    _TILE_CACHE[key] = tile
    return tile


def _paint_logo(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    logo_url: Optional[str],
    x: int,
    y: int,
    card_w: int,
    font_small: ImageFont.ImageFont,
) -> None:
    area_x, area_y = x + 6, y + 6
    area_w, area_h = card_w - 12, BANNER_AREA_H - 8
    painted = False

    if logo_url:
        tile = _logo_tile(logo_url, area_w, area_h)
        if tile is not None:
            img.paste(tile, (area_x, area_y), tile)
            painted = True

    if painted:
        return

    placeholder = Image.new("RGBA", (area_w, area_h), (0, 0, 0, 0))
    ImageDraw.Draw(placeholder).rounded_rectangle(
        [0, 0, area_w - 1, area_h - 1],
        radius=BANNER_RADIUS,
        fill=(55, 50, 75, 255),
    )
    img.paste(placeholder, (area_x, area_y), placeholder)
    draw.text(
        (x + card_w // 2 - 36, y + BANNER_AREA_H // 2 - 6),
        "NO IMAGE",
        fill=(120, 120, 140),
        font=font_small,
    )


def _draw_card(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    fonts: Dict[str, ImageFont.ImageFont],
    layout: Dict[str, Any],
    x: int,
    y: int,
    card_w: int,
    card_h: int,
    now: int,
) -> None:
    banner = layout["banner"]
    draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=12, fill=(38, 38, 52))
    _paint_logo(img, draw, banner.get("banner_logo"), x, y, card_w, fonts["small"])

    kind = banner["banner_type"]
    label = TYPE_LABELS.get(kind, kind)
    font_badge, font_name = fonts["badge"], fonts["name"]
    font_small, font_section = fonts["small"], fonts["section"]
    font_chip, font_chip_sm = fonts["chip"], fonts["chip_sm"]

    content_left = x + INNER
    content_w = card_w - INNER * 2
    # El par badge+título se centra en el tercio del medio; si no cabe, en la tarjeta.
    mid_x = content_left + content_w // 3
    mid_w = content_w // 3 - 4
    badge_y = y + BANNER_AREA_H + 8
    label_w = _text_width(draw, label, font_badge)
    badge_w, badge_h = max(label_w + 14, 70), 18
    title = layout["title"]
    pair_w = badge_w + 6 + _text_width(draw, title, font_name)
    pair_x = mid_x + (mid_w - pair_w) // 2
    if pair_w > mid_w:
        pair_x = x + (card_w - pair_w) // 2

    draw.rounded_rectangle([pair_x, badge_y, pair_x + badge_w, badge_y + badge_h], radius=5, fill=TYPE_COLORS.get(kind, (100, 100, 100)))
    draw.text((pair_x + (badge_w - label_w) // 2, badge_y + 2), label, fill="white", font=font_badge)
    draw.text((pair_x + badge_w + 6, badge_y + 1), title, fill=(255, 200, 255), font=font_name)

    y_info = badge_y + badge_h + 8
    weapons, chars = layout["weapons"], layout["chars"]
    weapon_chip_w = max((_chip_content_width(draw, item, font_chip, font_chip_sm, "weapon") for item in weapons), default=70)
    char_chip_w = max((_chip_content_width(draw, item, font_chip, font_chip_sm, "character") for item in chars), default=70)
    weapon_chip_w, char_chip_w = max(weapon_chip_w, 70), max(char_chip_w, 70)

    timers = _banner_timers(banner, now)
    timer_w = [_measure_timer_chip(draw, lab, val, font_small)[0] for lab, val, _ in timers]
    left_timer_w = timer_w[0]
    right_timer_w = timer_w[1] if len(timer_w) > 1 else 0

    weapon_label, char_label = "FEATURED WEAPONS", "FEATURED CHARACTERS"
    weapon_label_w = _text_width(draw, weapon_label, font_section)
    char_label_w = _text_width(draw, char_label, font_section)
    col_left_w = max(weapon_chip_w, left_timer_w, weapon_label_w, 70)
    col_right_w = max(char_chip_w, right_timer_w, char_label_w, 70)

    pair_w = col_left_w + LIST_GAP + col_right_w
    if pair_w <= content_w:
        col_left_x = content_left + (content_w - pair_w) // 2
        col_right_x = col_left_x + col_left_w + LIST_GAP
    else:
        col_left_w = max(70, int(col_left_w * (content_w / pair_w)))
        col_right_w = content_w - LIST_GAP - col_left_w
        col_left_x, col_right_x = content_left, content_left + col_left_w + LIST_GAP
        weapon_chip_w = min(weapon_chip_w, col_left_w)
        char_chip_w = min(char_chip_w, col_right_w)

    # Un solo timer: centrado en toda la tarjeta. Dos: uno por columna.
    spans = [(content_left, content_w)] if len(timers) == 1 else [(col_left_x, col_left_w), (col_right_x, col_right_w)]
    timer_bottom = y_info
    for (lab, val, color), (span_x, span_w) in zip(timers, spans):
        chip_w, chip_h = _measure_timer_chip(draw, lab, val, font_small)
        chip_w = min(chip_w, span_w)
        _draw_timer_chip(draw, span_x + (span_w - chip_w) // 2, y_info, lab, val, color, font_small, max_width=span_w)
        timer_bottom = max(timer_bottom, y_info + chip_h)

    y_list = timer_bottom + 8
    draw.text((col_left_x + (col_left_w - weapon_label_w) // 2, y_list), weapon_label, fill=(150, 255, 180), font=font_section)
    draw.text((col_right_x + (col_right_w - char_label_w) // 2, y_list), char_label, fill=(255, 220, 130), font=font_section)

    weapon_chip_w = min(weapon_chip_w, col_left_w)
    char_chip_w = min(char_chip_w, col_right_w)
    for items, kind, col_x, col_w, chip_w in (
        (weapons, "weapon", col_left_x, col_left_w, weapon_chip_w),
        (chars, "character", col_right_x, col_right_w, char_chip_w),
    ):
        cursor = y_list + 16
        for item in items:
            cursor += CHIP_GAP + _draw_item_chip(
                draw, col_x + (col_w - chip_w) // 2, cursor, chip_w, item, font_chip, font_chip_sm, kind=kind
            )


def _draw_footer(draw: ImageDraw.ImageDraw, width: int, height: int, disclaimer: str, font: ImageFont.ImageFont) -> None:
    footer_y = height - FOOTER_H
    draw.rectangle([0, footer_y, width, height], fill=(18, 18, 24))
    if _text_width(draw, disclaimer, font) <= width - PADDING * 2:
        rows = [(disclaimer, 12)]
    else:
        words = disclaimer.split(" ")
        mid = len(words) // 2
        rows = [(" ".join(words[:mid]), 6), (" ".join(words[mid:]), 18)]
    for line, dy in rows:
        draw.text(((width - _text_width(draw, line, font)) // 2, footer_y + dy), line, fill=(140, 140, 155), font=font)


def create_gacha_banner_image(active_banners: List[Dict[str, Any]], relative: bool = False) -> Optional[str]:
    """PNG de los banners activos.

    ``relative`` no cambia el dibujo (la cuenta atrás del arte es absoluta).
    Se acepta igual para no romper llamadas que ya lo pasan.
    """
    if not active_banners:
        return None

    now = now_as_unix()
    _prefetch_logos(active_banners)
    fonts = _load_fonts()
    card_w, layouts, row_heights, width, height = _plan_canvas(active_banners, fonts)
    disclaimer = (
        "[Akatsuki Games Inc], [Akatsuki], [Production I.G], and [Tōhō] are not affiliated "
        "with this project and are the owners of the attached elements."
    )

    img = Image.new("RGB", (width, height), color=(22, 22, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, HEADER_H], fill=(142, 36, 170))
    draw.text((PADDING, 12), "KAIJU NO. 8  •  ACTIVE GACHAS", fill="white", font=fonts["title"])

    y_row = HEADER_H + PADDING
    for row, row_h in enumerate(row_heights):
        for col in range(COLS):
            index = row * COLS + col
            if index >= len(layouts):
                break
            x = PADDING + col * (card_w + GAP)
            _draw_card(img, draw, fonts, layouts[index], x, y_row, card_w, row_h, now)
        y_row += row_h + GAP

    _draw_footer(draw, width, height, disclaimer, fonts["disclaimer"])
    os.makedirs(os.path.dirname(GACHA_IMAGE_PATH), exist_ok=True)
    tmp_path = GACHA_IMAGE_PATH + ".tmp"
    img.save(tmp_path, format="PNG", optimize=True)
    os.replace(tmp_path, GACHA_IMAGE_PATH)  # atomico: nunca se lee un PNG a medio escribir
    return GACHA_IMAGE_PATH


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
