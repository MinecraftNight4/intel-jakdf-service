# cogs/calendar/item_gachas.py
import hashlib
import io
import os
import re
import requests
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont
from discord import File, ui

from .helpers import (
    NEWS_FILE,
    fetchjson,
    format_time_view,
    now_as_unix,
)
from .base import add_navigation_buttons

JST = ZoneInfo("Asia/Tokyo")
GACHA_IMAGE_PATH = "sys_save/calendar/gacha.png"
GACHA_IMAGE_NAME = "gacha.png"
FONT_PATH = "sys_save/calendar/bungee-regular.ttf"

# ============================================================
# EXTRACTORES
# ============================================================

def extract_5star_chars(text: str) -> List[str]:
    found: List[str] = []
    pattern = r"(\[[^\]]+\]\s*[A-Za-z0-9\s\-']+?)(?:\s*\(Optimal|\s*$|\n)"
    for m in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
        name = re.sub(r"\s+", " ", m.group(1).strip())
        if 5 < len(name) < 80 and name not in found:
            found.append(name)
    return found[:8]

def extract_5star_weapons(text: str) -> List[str]:
    found: List[str] = []
    pattern = r"((?:HM|SH|AR|GS|Lc|SW|Ax|RF|AW|GG|SB|Fs|T|S)-[A-Za-z0-9\-]+)"
    for m in re.finditer(pattern, text):
        name = m.group(1).strip()
        if name not in found:
            found.append(name)
    return found[:8]

def detect_gacha_type(name: str, kind: str) -> str:
    """kind viene del filtro de plantilla: gacha | event | special."""
    name_up = name.upper()
    if kind == "event":
        return "EVENT"
    if kind == "special" or "PAID-ONLY" in name_up or "PAID ONLY" in name_up:
        return "PAID-ONLY"
    if "[LIMITED]" in name_up or "LIMITED" in name_up:
        return "LIMITED"
    return "STANDARD"

def clean_gacha_name(name: str) -> str:
    return (
        name.replace("PAID-ONLY ★5 ", "")
        .replace("PAID-ONLY ", "")
        .replace("[LIMITED] ", "")
        .replace(" PICKUP", "")
        .replace(" GACHA", "")
        .replace(" RERUN", "")
        .replace(" NOW AVAILABLE!", "")
        .replace("ANNIVERSARY ", "")
        .replace(" EVENT", "")
        .strip()
    )

def unix_jst_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=JST).strftime("%Y-%m-%d")

def remaining_label(end: Optional[int], now: int) -> str:
    if end is None:
        return "N/A"
    if end <= now:
        return "OFFLINE!"
    sec = end - now
    d = sec // 86400
    h = (sec % 86400) // 3600
    m = (sec % 3600) // 60
    return f"{d}d {h}h {m}m"

# ============================================================
# FILTRO DE PLANTILLAS
# ============================================================

def classify_article(art: dict) -> Optional[Dict[str, Any]]:
    """
    Solo acepta noticias que encajan en las plantillas reales de gacha.
    Devuelve None si es un informe / coming soon / no válido.
    """
    article_item = art.get("article_item") or []
    article_unix = art.get("article_unix") or []
    article_text = "\n".join(str(i) for i in article_item).lower()

    try:
        rule_unix = sorted(int(u) for u in article_unix if u is not None)
    except (ValueError, TypeError):
        return None

    rule_pull = "__availability period__" in article_text
    rule_shop = "exchange period" in article_text

    # 1) Gacha normal / limited / paid con exchange → 3 unix + pull + shop
    if rule_pull and rule_shop and len(rule_unix) == 3:
        release, end_gacha, end_exchange = rule_unix
        return {
            "kind": "gacha",
            "release": release,
            "end_gacha": end_gacha,
            "end_exchange": end_exchange,
            "end_event": None,
        }

    # 2) Evento con gacha → 3 unix + pull + !shop
    if rule_pull and not rule_shop and len(rule_unix) == 3:
        release, end_event, end_gacha = rule_unix
        return {
            "kind": "event",
            "release": release,
            "end_gacha": end_gacha,
            "end_exchange": None,
            "end_event": end_event,
        }

    # 3) Especial / paid-only corto → 2 unix + pull + !shop
    if rule_pull and not rule_shop and len(rule_unix) == 2:
        release, end_gacha = rule_unix
        return {
            "kind": "special",
            "release": release,
            "end_gacha": end_gacha,
            "end_exchange": None,
            "end_event": None,
        }

    return None

# ============================================================
# RECOLECCIÓN DE BANNERS ACTIVOS
# ============================================================

def get_active_gacha_info(art: dict, now: int) -> List[Dict[str, Any]]:
    info = classify_article(art)
    if info is None:
        return []

    raw_name = (art.get("article_name") or "")
    full_text = "\n".join(str(x) for x in (art.get("article_item") or []))
    logo = art.get("article_logo")
    chars = extract_5star_chars(full_text)
    weapons = extract_5star_weapons(full_text)
    gacha_type = detect_gacha_type(raw_name, info["kind"])
    clean_name = clean_gacha_name(raw_name.upper())

    end_gacha = info["end_gacha"]
    end_exchange = info["end_exchange"]
    end_event = info["end_event"]

    # ¿Sigue siendo relevante?
    # PAID / SPECIAL → solo gacha
    # LIMITED / STANDARD → gacha o exchange
    # EVENT → evento o gacha
    still_active = False
    if gacha_type == "PAID-ONLY":
        still_active = end_gacha > now
    elif gacha_type == "EVENT":
        still_active = (end_event and end_event > now) or end_gacha > now
    else:  # LIMITED / STANDARD
        still_active = end_gacha > now or (end_exchange is not None and end_exchange > now)

    # Si ya terminó TODO → se incluye igual con DISABLED! (según pedido del usuario)
    # Si prefieres ocultarlos del todo, cambia a: if not still_active: return []
    # Por ahora: se muestran aunque estén DISABLED! para que el usuario los vea.
    # Si quieres solo activos, descomenta la siguiente línea:
    # if not still_active:
    #     return []

    # Si NO hay nada pendiente, no listar (evita spam de DISABLED antiguos)
    if not still_active:
        return []

    return [{
        "name": clean_name,
        "type": gacha_type,
        "banner_end": end_gacha,
        "exchange_end": end_exchange,
        "event_end": end_event,
        "chars": chars,
        "weapons": weapons,
        "logo": logo,
    }]

def collect_active_banners() -> List[Dict[str, Any]]:
    news = fetchjson(NEWS_FILE, {})
    now = now_as_unix()
    active: List[Dict[str, Any]] = []
    for art in news.values():
        if (art.get("article_type") or "").lower() != "gacha":
            continue
        active.extend(get_active_gacha_info(art, now))
    active.sort(key=lambda x: x["banner_end"])
    return active

# ============================================================
# HELPERS DE DIBUJO
# ============================================================

def _load_font(size: int) -> ImageFont.ImageFont:
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
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]

def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    if max_width < 20:
        return [text]
    words = text.split()
    lines: List[str] = []
    current = ""

    def flush_long_word(word: str) -> None:
        nonlocal current
        chunk = ""
        for ch in word:
            trial = chunk + ch
            if _text_width(draw, trial, font) <= max_width:
                chunk = trial
            else:
                if chunk:
                    lines.append(chunk)
                chunk = ch
        current = chunk

    for word in words:
        trial = word if not current else f"{current} {word}"
        if _text_width(draw, trial, font) <= max_width:
            current = trial
            continue
        if current:
            lines.append(current)
        if _text_width(draw, word, font) <= max_width:
            current = word
        else:
            flush_long_word(word)
    if current:
        lines.append(current)
    return lines

def _item_lines(draw: ImageDraw.ImageDraw, items: List[str], font: ImageFont.ImageFont, max_width: int) -> List[str]:
    out: List[str] = []
    hang = "  "
    for item in items:
        wrapped = _wrap_text(draw, f"- {item}", font, max_width)
        if not wrapped:
            continue
        out.append(wrapped[0])
        for extra in wrapped[1:]:
            out.extend(_wrap_text(draw, hang + extra, font, max_width) or [hang + extra])
    return out

# ============================================================
# GENERACIÓN DE IMAGEN
# ============================================================

def _content_bbox(img: Image.Image, threshold: int = 28) -> Tuple[int, int, int, int]:
    """Bounding box del contenido no-negro (recorta barras negras del arte)."""
    rgb = img.convert("RGB")
    w, h = rgb.size
    pixels = rgb.load()
    min_x, min_y, max_x, max_y = w, h, -1, -1
    # Muestreo por filas/columnas para velocidad
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            if r > threshold or g > threshold or b > threshold:
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return (0, 0, w, h)
    # pequeño margen
    pad = 2
    return (
        max(0, min_x - pad),
        max(0, min_y - pad),
        min(w, max_x + 1 + pad),
        min(h, max_y + 1 + pad),
    )


def _get_dominant_color(img: Image.Image) -> Tuple[int, int, int]:
    """
    Color dominante del banner promocional (ignora negros/blancos).
    Prioriza tonos saturados para rellenar laterales en lugar de negro.
    """
    try:
        small = img.convert("RGB").resize((80, 80), Image.Resampling.LANCZOS)
        pixels = list(small.getdata())
        buckets: Dict[Tuple[int, int, int], float] = {}
        for r, g, b in pixels:
            mx, mn = max(r, g, b), min(r, g, b)
            if mx < 40 or mn > 235:
                continue
            sat = (mx - mn) / (mx + 1e-6)
            lum = (r + g + b) / 3.0
            if sat < 0.08 and lum < 50:
                continue
            # quantize ligeramente para agrupar
            key = (r // 12 * 12, g // 12 * 12, b // 12 * 12)
            # peso: saturación + luminosidad media
            weight = 1.0 + sat * 3.0 + (0.5 if 50 < lum < 180 else 0.0)
            buckets[key] = buckets.get(key, 0.0) + weight
        if not buckets:
            n = len(pixels) or 1
            return (
                max(45, sum(p[0] for p in pixels) // n),
                max(45, sum(p[1] for p in pixels) // n),
                max(45, sum(p[2] for p in pixels) // n),
            )
        best = max(buckets.items(), key=lambda kv: kv[1])[0]
        # suavizar un poco hacia el promedio de los top
        top_keys = sorted(buckets.items(), key=lambda kv: -kv[1])[:3]
        total_w = sum(w for _, w in top_keys) or 1.0
        r = int(sum(k[0] * w for k, w in top_keys) / total_w)
        g = int(sum(k[1] * w for k, w in top_keys) / total_w)
        b = int(sum(k[2] * w for k, w in top_keys) / total_w)
        return (max(r, 40), max(g, 40), max(b, 40))
    except Exception:
        return (55, 50, 75)


def _color_from_key(key: str) -> Tuple[int, int, int]:
    """
    Color determinista a partir de un string (p.ej. prefijo entre corchetes).
    Mismo texto → mismo color, sin necesidad de almacenarlo.
    Genera tonos saturados y legibles sobre fondo oscuro.
    """
    digest = hashlib.md5(key.strip().lower().encode("utf-8")).hexdigest()
    # Usar HSL-like: tono del hash, saturación alta, luminosidad media-alta
    hue = int(digest[0:4], 16) % 360
    sat = 0.55 + (int(digest[4:6], 16) % 30) / 100.0  # 0.55–0.84
    light = 0.42 + (int(digest[6:8], 16) % 18) / 100.0  # 0.42–0.59

    def hsl_to_rgb(h: float, s: float, l: float) -> Tuple[int, int, int]:
        c = (1 - abs(2 * l - 1)) * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = l - c / 2
        if h < 60:
            rp, gp, bp = c, x, 0.0
        elif h < 120:
            rp, gp, bp = x, c, 0.0
        elif h < 180:
            rp, gp, bp = 0.0, c, x
        elif h < 240:
            rp, gp, bp = 0.0, x, c
        elif h < 300:
            rp, gp, bp = x, 0.0, c
        else:
            rp, gp, bp = c, 0.0, x
        return (
            int((rp + m) * 255),
            int((gp + m) * 255),
            int((bp + m) * 255),
        )

    return hsl_to_rgb(float(hue), sat, light)


def _luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = [c / 255.0 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_border(fill: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Borde que contraste con el relleno del chip."""
    if _luminance(fill) > 0.45:
        return (30, 30, 40)
    return (220, 220, 235)


def _text_on_fill(fill: Tuple[int, int, int]) -> Tuple[int, int, int]:
    """Color de texto legible sobre el relleno."""
    return (20, 20, 28) if _luminance(fill) > 0.50 else (255, 255, 255)


def _parse_char_parts(raw: str) -> Tuple[Optional[str], str]:
    """Separa '[Prefijo] Nombre' → (prefijo_con_corchetes o None, nombre)."""
    m = re.match(r"^(\[[^\]]+\])\s*(.*)$", (raw or "").strip())
    if m:
        prefix = m.group(1).strip()
        name = (m.group(2) or "").strip() or prefix
        return prefix, name
    return None, (raw or "").strip()


def _rounded_mask(w: int, h: int, radius: int) -> Image.Image:
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return mask


def _fit_single_line(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Una sola línea; si no cabe, recorta con ellipsis (nunca NEWLINE)."""
    text = (text or "").replace("\n", " ").strip()
    if not text:
        return ""
    if _text_width(draw, text, font) <= max_width:
        return text
    ell = "…"
    while text and _text_width(draw, text + ell, font) > max_width:
        text = text[:-1]
    return (text + ell) if text else ell


def _measure_timer_chip(
    draw: ImageDraw.ImageDraw,
    label: str,
    value: str,
    font: ImageFont.ImageFont,
) -> Tuple[int, int]:
    pad_x, pad_y = 10, 6
    text = f"{label}: {value}"
    tw = _text_width(draw, text, font)
    return tw + pad_x * 2, 14 + pad_y * 2


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
    """
    Chip de contador. Texto completo siempre visible (sin ellipsis).
    Solo DISABLED! va en rojo.
    """
    pad_y = 6
    radius = 6
    label_part = f"{label}: "
    text_full = label_part + value
    # padding horizontal adaptable para que quepa el texto entero
    pad_x = 10
    natural_w = _text_width(draw, text_full, font) + pad_x * 2
    chip_w = natural_w
    if max_width is not None and chip_w > max_width:
        # reducir padding al mínimo antes de tocar el texto
        pad_x = 4
        chip_w = _text_width(draw, text_full, font) + pad_x * 2
        if chip_w > max_width:
            chip_w = max_width  # último recurso: el texto igual se dibuja completo
    chip_h = 14 + pad_y * 2

    fill = (48, 50, 68)
    border = (110, 115, 150)
    draw.rounded_rectangle(
        [x, y, x + chip_w, y + chip_h],
        radius=radius,
        fill=fill,
        outline=border,
        width=2,
    )
    lw = _text_width(draw, label_part, font)
    draw.text((x + pad_x, y + pad_y), label_part, fill=label_color, font=font)
    val_color = (255, 55, 55) if value == "OFFLINE!" else label_color
    draw.text((x + pad_x + lw, y + pad_y), value, fill=val_color, font=font)
    return chip_w, chip_h


def _draw_item_chip(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    text: str,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
    kind: str = "weapon",
) -> int:
    """
    Chip a ancho fijo `w`, texto centrado.
    Personajes (estilo invertido):
      - fondo gris oscuro uniforme
      - borde + letras con el color del prefijo
    Armas:
      - fondo gris, texto claro, borde neutro
    """
    pad_x, pad_y = 8, 5
    radius = 6
    gap_inner = 2
    max_text_w = max(20, w - pad_x * 2)

    gray_fill = (48, 50, 64)
    neutral_border = (110, 115, 140)

    if kind == "character":
        prefix, name = _parse_char_parts(text)
        if prefix:
            accent = _color_from_key(prefix)
            prefix_s = _fit_single_line(draw, prefix, font_small, max_text_w)
            name_s = _fit_single_line(draw, name, font, max_text_w)
            line_h = 14
            chip_h = pad_y * 2 + line_h * 2 + gap_inner

            draw.rounded_rectangle(
                [x, y, x + w, y + chip_h],
                radius=radius,
                fill=gray_fill,
                outline=accent,
                width=2,
            )
            pw = _text_width(draw, prefix_s, font_small)
            nw = _text_width(draw, name_s, font)
            draw.text((x + (w - pw) // 2, y + pad_y), prefix_s, fill=accent, font=font_small)
            draw.text(
                (x + (w - nw) // 2, y + pad_y + line_h + gap_inner),
                name_s,
                fill=accent,
                font=font,
            )
            return chip_h
        else:
            text = name
            accent = _color_from_key(text)
            text_s = _fit_single_line(draw, text, font, max_text_w)
            chip_h = pad_y * 2 + 16
            draw.rounded_rectangle(
                [x, y, x + w, y + chip_h],
                radius=radius,
                fill=gray_fill,
                outline=accent,
                width=2,
            )
            tw = _text_width(draw, text_s, font)
            draw.text((x + (w - tw) // 2, y + pad_y), text_s, fill=accent, font=font)
            return chip_h

    # Weapon
    text_s = _fit_single_line(draw, text, font, max_text_w)
    chip_h = pad_y * 2 + 16
    draw.rounded_rectangle(
        [x, y, x + w, y + chip_h],
        radius=radius,
        fill=gray_fill,
        outline=neutral_border,
        width=2,
    )
    tw = _text_width(draw, text_s, font)
    draw.text((x + (w - tw) // 2, y + pad_y), text_s, fill=(210, 215, 230), font=font)
    return chip_h


def _chip_content_width(
    measure: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    font_small: ImageFont.ImageFont,
    kind: str,
) -> int:
    """Ancho natural del contenido del chip (sin forzar estirado)."""
    pad = 16
    if kind == "character":
        prefix, name = _parse_char_parts(text)
        if prefix:
            return max(
                _text_width(measure, prefix, font_small),
                _text_width(measure, name, font),
            ) + pad
        return _text_width(measure, name, font) + pad
    return _text_width(measure, text, font) + pad


def create_gacha_banner_image(active_banners: List[Dict[str, Any]], relative: bool = False) -> Optional[str]:
    if not active_banners:
        return None

    COLS = 3
    MIN_CARD_W = 400
    MAX_CARD_W = 600
    PADDING = 12
    GAP = 10
    HEADER_H = 48
    BANNER_AREA_H = 118
    BANNER_RADIUS = 10
    INNER = 12
    LINE_H = 18
    CHIP_GAP = 5
    COL_GAP = 14
    TIMER_GAP = 10
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

    font_title = _load_font(20)
    font_name = _load_font(14)
    font_small = _load_font(12)
    font_badge = _load_font(12)
    font_chip = _load_font(11)
    font_chip_sm = _load_font(10)
    font_section = _load_font(11)

    measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    now = now_as_unix()

    # Ancho de tarjeta: que quepa título, timers y chips SIN recortar texto
    max_title_w = 0
    max_chip_w = 0
    max_timer_w = 0
    for banner in active_banners:
        max_title_w = max(max_title_w, _text_width(measure, banner["name"], font_name))
        for wpn in (banner.get("weapons") or []):
            max_chip_w = max(
                max_chip_w,
                _chip_content_width(measure, wpn, font_chip, font_chip_sm, "weapon"),
            )
        for ch in (banner.get("chars") or []):
            max_chip_w = max(
                max_chip_w,
                _chip_content_width(measure, ch, font_chip, font_chip_sm, "character"),
            )
        # timers típicos
        # peor caso de etiqueta + tiempo para dimensionar columnas
        worst_time = "99d 99h 99m"
        for sample in (
            f"Banner: {worst_time}",
            f"Exchange: {worst_time}",
            f"Event: {worst_time}",
            f"Gacha: {worst_time}",
        ):
            max_timer_w = max(max_timer_w, _text_width(measure, sample, font_small) + 24)

    sec_w = max(
        _text_width(measure, "FEATURED WEAPONS", font_section),
        _text_width(measure, "FEATURED CHARACTERS", font_section),
    )
    col_need = max(max_chip_w, max_timer_w, sec_w + 4, 110)
    need_cols = INNER * 2 + col_need * 3 + 12
    need_title = 90 + 10 + max_title_w + INNER * 2
    CARD_W = max(MIN_CARD_W, min(MAX_CARD_W, max(need_cols, need_title)))

    usable = CARD_W - INNER * 2 - COL_GAP
    col_w = usable // 2
    name_w = CARD_W - 100 - INNER  # espacio título al lado del badge

    def _est_chip_h(item: str, kind: str) -> int:
        if kind == "character":
            prefix, _ = _parse_char_parts(item)
            return 38 if prefix else 26
        return 26

    layouts: List[Dict[str, Any]] = []
    for banner in active_banners:
        # Título en UNA línea; si no cabe se recorta, pero name_w es generoso
        title_one = _fit_single_line(measure, banner["name"], font_name, name_w)
        weapons = banner.get("weapons") or []
        chars = banner.get("chars") or []

        # Ancho de chips = max(contenido de la columna, mínimo legible), sin pasarse de col_w
        wpn_natural = max(
            (_chip_content_width(measure, w, font_chip, font_chip_sm, "weapon") for w in weapons),
            default=80,
        )
        char_natural = max(
            (_chip_content_width(measure, ch, font_chip, font_chip_sm, "character") for ch in chars),
            default=80,
        )
        wpn_chip_w = min(col_w, max(wpn_natural, 90))
        char_chip_w = min(col_w, max(char_natural, 90))

        w_h = sum(_est_chip_h(w, "weapon") + CHIP_GAP for w in weapons) if weapons else 14
        c_h = sum(_est_chip_h(ch, "character") + CHIP_GAP for ch in chars) if chars else 14
        list_h = max(w_h, c_h, 14)

        body_h = (
            BANNER_AREA_H
            + 10
            + 22          # badge + title
            + 8
            + 30          # timers
            + 6
            + 16          # section labels
            + 4
            + list_h
            + INNER
        )
        layouts.append({
            "banner": banner,
            "title": title_one,
            "weapons": weapons,
            "chars": chars,
            "wpn_chip_w": wpn_chip_w,
            "char_chip_w": char_chip_w,
            "height": body_h,
        })

    row_heights: List[int] = []
    rows = (len(layouts) + COLS - 1) // COLS
    for r in range(rows):
        chunk = layouts[r * COLS:(r + 1) * COLS]
        row_h = max(c["height"] for c in chunk)
        for c in chunk:
            c["height"] = row_h
        row_heights.append(row_h)

    width = PADDING * 2 + COLS * CARD_W + (COLS - 1) * GAP
    height = HEADER_H + PADDING + sum(row_heights) + max(0, rows - 1) * GAP + PADDING

    img = Image.new("RGB", (width, height), color=(22, 22, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, width, HEADER_H], fill=(142, 36, 170))
    draw.text((PADDING, 12), "KAIJU NO. 8  •  ACTIVE GACHAS", fill="white", font=font_title)

    y_row = HEADER_H + PADDING
    for r in range(rows):
        row_h = row_heights[r]
        for c in range(COLS):
            idx = r * COLS + c
            if idx >= len(layouts):
                break
            layout = layouts[idx]
            banner = layout["banner"]
            x = PADDING + c * (CARD_W + GAP)
            y = y_row
            card_h = row_h

            draw.rounded_rectangle([x, y, x + CARD_W, y + card_h], radius=12, fill=(38, 38, 52))

            # --- Banner: 1) color dominante  2) rellenar área  3) poner logo encima ---
            area_x0, area_y0 = x + 6, y + 6
            area_w, area_h = CARD_W - 12, BANNER_AREA_H - 8
            logo_url = banner.get("logo")
            drew_image = False

            if logo_url:
                try:
                    resp = requests.get(logo_url, timeout=5)
                    if resp.status_code == 200:
                        logo = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                        # Recortar barras negras del archivo promocional si existen
                        bbox = _content_bbox(logo, threshold=25)
                        if bbox[2] - bbox[0] > 10 and bbox[3] - bbox[1] > 10:
                            logo = logo.crop(bbox)

                        # 1) Color dominante de la imagen
                        dom = _get_dominant_color(logo)

                        # 2) Rellenar TODO el área con ese color (nunca negro residual)
                        bg = Image.new("RGBA", (area_w, area_h), (0, 0, 0, 0))
                        bg_draw = ImageDraw.Draw(bg)
                        bg_draw.rounded_rectangle(
                            [0, 0, area_w - 1, area_h - 1],
                            radius=BANNER_RADIUS,
                            fill=(dom[0], dom[1], dom[2], 255),
                        )

                        # 3) Imagen centrada ENCIMA (sin estirar), con alpha correcto
                        lw, lh = logo.size
                        if lw > 0 and lh > 0:
                            scale = min(area_w / lw, area_h / lh)
                            new_w = max(1, int(lw * scale))
                            new_h = max(1, int(lh * scale))
                            logo_r = logo.resize((new_w, new_h), Image.Resampling.LANCZOS)
                            px = (area_w - new_w) // 2
                            py = (area_h - new_h) // 2

                            # Componer sobre el fondo de color dominante (evita negro por alpha)
                            composed = bg.copy()
                            composed.paste(logo_r, (px, py), logo_r)
                            # Recortar a esquinas redondeadas
                            mask = _rounded_mask(area_w, area_h, BANNER_RADIUS)
                            composed.putalpha(mask)
                            img.paste(composed, (area_x0, area_y0), composed)
                            drew_image = True
                        else:
                            img.paste(bg, (area_x0, area_y0), bg)
                            drew_image = True
                except Exception:
                    pass

            if not drew_image:
                ph = Image.new("RGBA", (area_w, area_h), (0, 0, 0, 0))
                ph_draw = ImageDraw.Draw(ph)
                ph_draw.rounded_rectangle(
                    [0, 0, area_w - 1, area_h - 1],
                    radius=BANNER_RADIUS,
                    fill=(55, 50, 75, 255),
                )
                img.paste(ph, (area_x0, area_y0), ph)
                draw.text(
                    (x + CARD_W // 2 - 36, y + BANNER_AREA_H // 2 - 6),
                    "NO IMAGE",
                    fill=(120, 120, 140),
                    font=font_small,
                )

            gtype = banner["type"]
            display_label = TYPE_LABELS.get(gtype, gtype)
            badge_color = TYPE_COLORS.get(gtype, (100, 100, 100))

            # === 3 columnas iguales del área de contenido ===
            content_left = x + INNER
            content_w = CARD_W - INNER * 2
            third = content_w // 3
            col1_x = content_left
            col2_x = content_left + third
            col3_x = content_left + third * 2
            col_w1 = third - 4
            col_w2 = third - 4
            col_w3 = third - 4

            # --- Fila central: badge + título centrados en columna 2 ---
            badge_y = y + BANNER_AREA_H + 8
            label_w = _text_width(draw, display_label, font_badge)
            badge_w = max(label_w + 14, 70)
            badge_h = 18
            title = layout["title"]
            title_w = _text_width(draw, title, font_name)
            pair_w = badge_w + 6 + title_w
            pair_x = col2_x + (col_w2 - pair_w) // 2
            # Si el par no cabe en col2, centrar respecto a toda la tarjeta
            if pair_w > col_w2:
                pair_x = x + (CARD_W - pair_w) // 2

            draw.rounded_rectangle(
                [pair_x, badge_y, pair_x + badge_w, badge_y + badge_h],
                radius=5,
                fill=badge_color,
            )
            draw.text(
                (pair_x + (badge_w - label_w) // 2, badge_y + 2),
                display_label,
                fill="white",
                font=font_badge,
            )
            draw.text(
                (pair_x + badge_w + 6, badge_y + 1),
                title,
                fill=(255, 200, 255),
                font=font_name,
            )

            y_info = badge_y + badge_h + 8

            # --- Timers: col1 = izquierdo, col3 = derecho; si solo 1 → centrado en col2 ---
            timers: List[Tuple[str, str, Tuple[int, int, int]]] = []
            if gtype == "PAID-ONLY":
                timers.append(("Gacha", remaining_label(banner["banner_end"], now), (170, 210, 255)))
            elif gtype == "EVENT":
                timers.append(("Event", remaining_label(banner.get("event_end"), now), (150, 255, 180)))
                timers.append(("Gacha", remaining_label(banner["banner_end"], now), (170, 210, 255)))
            else:
                timers.append(("Banner", remaining_label(banner["banner_end"], now), (170, 210, 255)))
                timers.append(("Exchange", remaining_label(banner.get("exchange_end"), now), (255, 190, 130)))

            timer_bottom = y_info
            if len(timers) == 1:
                lb, val, col = timers[0]
                cw, ch = _measure_timer_chip(draw, lb, val, font_small)
                cw = min(cw, col_w2)
                tx = col2_x + (col_w2 - cw) // 2
                _draw_timer_chip(draw, tx, y_info, lb, val, col, font_small, max_width=col_w2)
                timer_bottom = y_info + ch
            else:
                (lb1, val1, col1), (lb2, val2, col2c) = timers[0], timers[1]
                cw1, ch1 = _measure_timer_chip(draw, lb1, val1, font_small)
                cw2, ch2 = _measure_timer_chip(draw, lb2, val2, font_small)
                cw1 = min(cw1, col_w1)
                cw2 = min(cw2, col_w3)
                tx1 = col1_x + (col_w1 - cw1) // 2
                tx2 = col3_x + (col_w3 - cw2) // 2
                _draw_timer_chip(draw, tx1, y_info, lb1, val1, col1, font_small, max_width=col_w1)
                _draw_timer_chip(draw, tx2, y_info, lb2, val2, col2c, font_small, max_width=col_w3)
                timer_bottom = y_info + max(ch1, ch2)

            # --- FEATURED WEAPONS (col1) / FEATURED CHARACTERS (col3) ---
            y_list = timer_bottom + 8
            wpn_label = "FEATURED WEAPONS"
            char_label = "FEATURED CHARACTERS"
            ww = _text_width(draw, wpn_label, font_section)
            cw = _text_width(draw, char_label, font_section)
            draw.text(
                (col1_x + (col_w1 - ww) // 2, y_list),
                wpn_label,
                fill=(150, 255, 180),
                font=font_section,
            )
            draw.text(
                (col3_x + (col_w3 - cw) // 2, y_list),
                char_label,
                fill=(255, 220, 130),
                font=font_section,
            )

            # Chips a ancho de columna (texto completo; ellipsis solo si no cabe ni así)
            wpn_chip_w = col_w1
            char_chip_w = col_w3

            cy = y_list + 16
            for wpn in layout["weapons"]:
                chip_x = col1_x + (col_w1 - wpn_chip_w) // 2
                used = _draw_item_chip(
                    draw, chip_x, cy, wpn_chip_w, wpn, font_chip, font_chip_sm, kind="weapon"
                )
                cy += used + CHIP_GAP

            cy = y_list + 16
            for ch in layout["chars"]:
                chip_x = col3_x + (col_w3 - char_chip_w) // 2
                used = _draw_item_chip(
                    draw, chip_x, cy, char_chip_w, ch, font_chip, font_chip_sm, kind="character"
                )
                cy += used + CHIP_GAP

        y_row += row_h + GAP

    os.makedirs(os.path.dirname(GACHA_IMAGE_PATH), exist_ok=True)
    img.save(GACHA_IMAGE_PATH, format="PNG", optimize=True)
    return GACHA_IMAGE_PATH


def get_gacha_attachment() -> Optional[File]:
    if os.path.exists(GACHA_IMAGE_PATH):
        return File(GACHA_IMAGE_PATH, filename=GACHA_IMAGE_NAME)
    return None

# ============================================================
# PANEL DISCORD
# ============================================================

def panelbuilder_gachas(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x8E24AA)

    now = now_as_unix()
    container.add_item(ui.TextDisplay(f"## __AVAILABLE GACHAS__\n-# ℹ️ *Attachment generated <t:{now}:R>!*"))

    active_banners = collect_active_banners()

    if not active_banners:
        container.add_item(ui.TextDisplay("*This should be impossible, but currently the are no banners!?*"))
    else:
        gallery = ui.MediaGallery()
        gallery.add_item(media=f"attachment://{GACHA_IMAGE_NAME}")
        container.add_item(gallery)

        container.add_item(ui.Separator())

        future_gacha = [b for b in active_banners if b["banner_end"] > now]
        future_ex = [
            b for b in active_banners
            if b["type"] in ("LIMITED", "STANDARD")
            and b.get("exchange_end")
            and b["exchange_end"] > now
        ]
        future_event = [
            b for b in active_banners
            if b["type"] == "EVENT"
            and b.get("event_end")
            and b["event_end"] > now
        ]

        lines: List[str] = []

        if future_event:
            closest_day = min(unix_jst_day(b["event_end"]) for b in future_event)
            same_day = [b for b in future_event if unix_jst_day(b["event_end"]) == closest_day]
            ts = min(b["event_end"] for b in same_day)
            lines.append(f"## __Events departing {'on ' if not relative else ''}{format_time_view(ts, relative, 'f')}:__")
            seen = set()
            for b in same_day:
                if b["name"] not in seen:
                    seen.add(b["name"])
                    lines.append(f"- `{b['name']}`")

        if future_gacha:
            closest_day = min(unix_jst_day(b["banner_end"]) for b in future_gacha)
            same_day = [b for b in future_gacha if unix_jst_day(b["banner_end"]) == closest_day]
            ts = min(b["banner_end"] for b in same_day)
            lines.append(f"## __Gachas departing {'on ' if not relative else ''}{format_time_view(ts, relative, 'f')}:__")
            seen = set()
            for b in same_day:
                if b["name"] not in seen:
                    seen.add(b["name"])
                    lines.append(f"* `{b['name']}`")

        if future_ex:
            closest_day = min(unix_jst_day(b["exchange_end"]) for b in future_ex)
            same_day = [b for b in future_ex if unix_jst_day(b["exchange_end"]) == closest_day]
            ts = min(b["exchange_end"] for b in same_day)
            lines.append(f"## __Exchange departing {'on ' if not relative else ''}{format_time_view(ts, relative, 'f')}:__")
            chars: List[str] = []
            weapons: List[str] = []
            for b in same_day:
                for c in b.get("chars", []):
                    if c not in chars:
                        chars.append(c)
                for w in b.get("weapons", []):
                    if w not in weapons:
                        weapons.append(w)
            for c in chars:
                lines.append(f"- `{c}`")
            for w in weapons:
                lines.append(f"- `{w}`")

        if lines:
            container.add_item(ui.TextDisplay("\n".join(lines).strip()))

    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="gachas", relative=relative)
    view.add_item(container)
    return view