# cogs/calendar/item_gachas.py
import io
import os
import re
import requests
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional
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


def detect_gacha_type(name: str) -> str:
    name_up = name.upper()
    if "PAID-ONLY" in name_up or "PAID ONLY" in name_up:
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
        .strip()
    )


def unix_jst_day(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=JST).strftime("%Y-%m-%d")


def remaining_label(end: int, now: int) -> str:
    if end <= now:
        return "Ended"
    sec = end - now
    return f"{sec // 86400}d {(sec % 86400) // 3600}h"


def get_active_gacha_info(art: dict, now: int) -> List[Dict[str, Any]]:
    raw_name = (art.get("article_name") or "").upper()
    unixes = [int(x) for x in (art.get("article_unix") or [])]
    full_text = "\n".join(str(x) for x in (art.get("article_item") or []))
    logo = art.get("article_logo")
    chars = extract_5star_chars(full_text)
    weapons = extract_5star_weapons(full_text)
    gacha_type = detect_gacha_type(raw_name)
    clean_name = clean_gacha_name(raw_name)
    results: List[Dict[str, Any]] = []

    def push(banner_end: int, exchange_end: Optional[int]) -> None:
        if banner_end > now or (exchange_end and exchange_end > now):
            results.append({
                "name": clean_name,
                "type": gacha_type,
                "banner_end": banner_end,
                "exchange_end": exchange_end,
                "chars": chars,
                "weapons": weapons,
                "logo": logo,
            })

    if len(unixes) >= 2:
        if len(unixes) <= 3:
            push(unixes[1], unixes[2] if len(unixes) > 2 else None)
        else:
            for i in range(0, len(unixes) - 1, 2):
                push(unixes[i + 1], None)
    elif unixes:
        push(max(unixes), None)

    return results


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


def create_gacha_banner_image(active_banners: List[Dict[str, Any]], relative: bool = False) -> Optional[str]:
    if not active_banners:
        return None

    COLS = 3
    CARD_W = 440
    PADDING = 16
    GAP = 14
    HEADER_H = 52
    BANNER_AREA_H = 118
    INNER = 12
    LINE_H = 17
    TYPE_COLORS = {
        "PAID-ONLY": (220, 50, 50),
        "LIMITED": (255, 150, 30),
        "STANDARD": (50, 150, 220),
    }

    font_title = _load_font(22)
    font_small = _load_font(13)
    font_badge = _load_font(11)

    measure = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    now = now_as_unix()

    col_w = (CARD_W - INNER * 2 - 12) // 2
    name_w = CARD_W - 120 - INNER

    layouts: List[Dict[str, Any]] = []
    for banner in active_banners:
        name_lines = _wrap_text(measure, banner["name"], font_small, name_w) or [banner["name"]]
        weapon_lines = _item_lines(measure, banner.get("weapons") or [], font_small, col_w)
        char_lines = _item_lines(measure, banner.get("chars") or [], font_small, col_w)
        list_rows = max(len(weapon_lines), len(char_lines), 1)
        name_h = max(22, len(name_lines) * LINE_H + 4)
        body_h = BANNER_AREA_H + 8 + name_h + 28 + 20 + list_rows * LINE_H + INNER
        layouts.append({
            "banner": banner,
            "name_lines": name_lines,
            "weapon_lines": weapon_lines,
            "char_lines": char_lines,
            "name_h": name_h,
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
    draw.text((PADDING, 13), "KAIJU NO. 8  •  ACTIVE GACHAS", fill="white", font=font_title)

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

            draw.rounded_rectangle([x, y, x + CARD_W, y + card_h], radius=10, fill=(38, 38, 52))

            logo_url = banner.get("logo")
            if logo_url:
                try:
                    resp = requests.get(logo_url, timeout=5)
                    if resp.status_code == 200:
                        logo = Image.open(io.BytesIO(resp.content)).convert("RGBA")
                        logo = logo.resize((CARD_W - 12, BANNER_AREA_H - 8), Image.Resampling.LANCZOS)
                        img.paste(logo, (x + 6, y + 6), logo)
                    else:
                        raise ValueError("bad status")
                except Exception:
                    draw.rectangle([x + 6, y + 6, x + CARD_W - 6, y + BANNER_AREA_H - 2], fill=(50, 50, 70))
                    draw.text((x + CARD_W // 2 - 40, y + 50), "NO IMAGE", fill=(120, 120, 140), font=font_small)
            else:
                draw.rectangle([x + 6, y + 6, x + CARD_W - 6, y + BANNER_AREA_H - 2], fill=(50, 50, 70))
                draw.text((x + CARD_W // 2 - 40, y + 50), "NO IMAGE", fill=(120, 120, 140), font=font_small)

            gtype = banner["type"]
            badge_color = TYPE_COLORS.get(gtype, (100, 100, 100))
            badge_y = y + BANNER_AREA_H + 6
            draw.rounded_rectangle([x + 8, badge_y, x + 108, badge_y + 18], radius=4, fill=badge_color)
            draw.text((x + 14, badge_y + 2), gtype, fill="white", font=font_badge)
            for i, line in enumerate(layout["name_lines"]):
                draw.text((x + 116, badge_y + i * LINE_H), line, fill=(255, 200, 255), font=font_small)

            y_info = badge_y + layout["name_h"]
            b_txt = remaining_label(banner["banner_end"], now)
            e_txt = remaining_label(banner["exchange_end"], now) if banner.get("exchange_end") else "N/A"
            draw.text((x + 10, y_info), f"Banner: {b_txt}", fill=(170, 210, 255), font=font_small)
            draw.text((x + 10 + col_w + 12, y_info), f"Exchange: {e_txt}", fill=(255, 190, 130), font=font_small)

            y_list = y_info + 26
            left_x = x + 10
            right_x = x + 10 + col_w + 12
            draw.text((left_x, y_list), "Weapons:", fill=(150, 255, 180), font=font_small)
            draw.text((right_x, y_list), "Characters:", fill=(255, 220, 130), font=font_small)
            for i, line in enumerate(layout["weapon_lines"]):
                draw.text((left_x, y_list + 18 + i * LINE_H), line, fill=(200, 200, 200), font=font_small)
            for i, line in enumerate(layout["char_lines"]):
                draw.text((right_x, y_list + 18 + i * LINE_H), line, fill=(200, 200, 200), font=font_small)

        y_row += row_h + GAP

    os.makedirs(os.path.dirname(GACHA_IMAGE_PATH), exist_ok=True)
    img.save(GACHA_IMAGE_PATH, format="PNG", optimize=True)
    return GACHA_IMAGE_PATH


def get_gacha_attachment() -> Optional[File]:
    if os.path.exists(GACHA_IMAGE_PATH):
        return File(GACHA_IMAGE_PATH, filename=GACHA_IMAGE_NAME)
    return None


def panelbuilder_gachas(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x8E24AA)

    container.add_item(ui.TextDisplay("## __AVAILABLE GACHAS__"))

    active_banners = collect_active_banners()
    now = now_as_unix()

    if not active_banners:
        container.add_item(ui.TextDisplay("*No active gacha banners found right now.*"))
    else:
        # Imagen DENTRO del layout (igual que las news feeds)
        gallery = ui.MediaGallery()
        gallery.add_item(media=f"attachment://{GACHA_IMAGE_NAME}")
        container.add_item(gallery)

        container.add_item(ui.Separator())

        # Solo el grupo más próximo a expirar (misma fecha JST)
        future_gacha = [b for b in active_banners if b["banner_end"] > now]
        future_ex = [b for b in active_banners if b.get("exchange_end") and b["exchange_end"] > now]

        lines: List[str] = []

        if future_gacha:
            closest_day = min(unix_jst_day(b["banner_end"]) for b in future_gacha)
            same_day = [b for b in future_gacha if unix_jst_day(b["banner_end"]) == closest_day]
            ts = min(b["banner_end"] for b in same_day)
            lines.append(f"## __Gachas leaving {format_time_view(ts, relative, 'f')}__")
            seen = set()
            for b in same_day:
                if b["name"] not in seen:
                    seen.add(b["name"])
                    lines.append(f"* `{b['name']}`")
            lines.append("")

        if future_ex:
            closest_day = min(unix_jst_day(b["exchange_end"]) for b in future_ex)
            same_day = [b for b in future_ex if unix_jst_day(b["exchange_end"]) == closest_day]
            ts = min(b["exchange_end"] for b in same_day)
            lines.append(f"## __Exchange leaving {format_time_view(ts, relative, 'f')}__")
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
                lines.append(f"* `{c}`")
            for w in weapons:
                lines.append(f"* `{w}`")
            lines.append("")

        if lines:
            container.add_item(ui.TextDisplay("\n".join(lines).strip()))

    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="gachas", relative=relative)
    view.add_item(container)
    return view