# cogs/calendar.py
# ============================================================
#  KAIJU NO. 8 - CALENDAR SYSTEM (pre-built cache)
# ============================================================

import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from calendar import monthrange
from typing import Dict, Any, List, Optional, Tuple

import discord
from discord import app_commands, ui
from discord.ext import commands
from logger import log

# ============================================================
#  CONFIGURACIÓN
# ============================================================
JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc

NEWS_FILE   = "sys_save/request_news.json"
XCOM_FILE   = "sys_save/request_xcom.json"
RMAP_FILE   = "sys_save/request_rmap.json"
PUBLIC_COOLDOWN = 60


# ============================================================
#  HELPERS DE TIEMPO (optimizados)
# ============================================================
def now_jst() -> datetime:
    return datetime.now(JST)

def now_unix() -> int:
    return int(time.time())

def to_unix(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp())

def GenerateUnixDay(h: int = 0, m: int = 0, s: int = 0) -> int:
    """Próximo (o de hoy si aún no ha pasado) momento a la hora h:m:s JST."""
    n = now_jst()
    target = n.replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return to_unix(target)

def GenerateUnixWeek(weekday: int = 7, h: int = 0, m: int = 0, s: int = 0) -> int:
    """
    weekday: 1=Lunes ... 7=Domingo
    Devuelve el próximo (o de esta semana si aún no ha pasado) día de la semana a h:m:s JST.
    """
    n = now_jst()
    target_weekday = (weekday - 1) % 7          # Python: 0=Lunes ... 6=Domingo
    days_ahead = (target_weekday - n.weekday()) % 7
    target = (n + timedelta(days=days_ahead)).replace(
        hour=h, minute=m, second=s, microsecond=0
    )
    if target <= n:
        target += timedelta(weeks=1)
    return to_unix(target)

def GenerateUnixMonth(h: int = 0, m: int = 0, s: int = 0) -> int:
    """Último día del mes actual (o del siguiente si ya pasó) a h:m:s JST."""
    n = now_jst()
    last_day = monthrange(n.year, n.month)[1]
    target = n.replace(day=last_day, hour=h, minute=m, second=s, microsecond=0)

    if target <= n:
        if n.month == 12:
            next_year, next_month = n.year + 1, 1
        else:
            next_year, next_month = n.year, n.month + 1
        last_day = monthrange(next_year, next_month)[1]
        target = datetime(next_year, next_month, last_day, h, m, s, tzinfo=JST)

    return to_unix(target)

def format_ts(ts: int, relative: bool = False, style: str = "f") -> str:
    if relative:
        return f"<t:{ts}:R>"
    return f"<t:{ts}:{style}>"

def FlavorTextOnTime(ts: int, pass_txt: str, ends_txt: str = "") -> str:
    now = now_unix()
    txt = ends_txt if ts < now else pass_txt
    return txt.replace("{time}", str(ts))


# ============================================================
#  CARGA DE DATOS
# ============================================================
def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default.copy() if isinstance(default, dict) else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, dict) else default


# ============================================================
#  SOON HELPERS
# ============================================================
def get_upcoming_events(limit: int = 3) -> List[Tuple[int, str]]:
    rmap = load_json(RMAP_FILE, {})
    candidates = []
    for data in rmap.values():
        formats = data.get("format", {})
        for ts_str, text in formats.items():
            try:
                ts = int(ts_str)
                if ts > now_unix():
                    candidates.append((ts, text.strip()))
            except ValueError:
                continue
    candidates.sort(key=lambda x: x[0])
    return candidates[:limit]

def get_best_roadmap_image() -> Optional[str]:
    rmap = load_json(RMAP_FILE, {})
    if rmap:
        best_id = max(rmap.keys(), key=lambda k: rmap[k].get("processed_at", 0))
        return rmap[best_id].get("display")
    # fallback a xcom
    xcom = load_json(XCOM_FILE, {})
    for account in xcom.values():
        roadmaps = account.get("roadmap", {})
        if roadmaps:
            best = max(roadmaps.values(), key=lambda r: r.get("post_at", 0))
            return best.get("preview")
    return None


# ============================================================
#  BUILDERS DE CADA SECCIÓN
# ============================================================

def _build_update_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    news = load_json(NEWS_FILE, {})
    now = now_unix()

    # Buscar el mantenimiento / update más relevante
    candidate = None
    for art in news.values():
        t = (art.get("article_type") or "").lower()
        if t not in ("update", "maintenance"):
            continue
        unixes = art.get("article_unix") or []
        if not unixes:
            continue
        if max(unixes) > now:          # aún vigente
            candidate = art
            break

    if candidate is None:
        # No hay nada → página vacía con mensaje
        container = ui.Container(accent_colour=0x546e7a)
        container.add_item(ui.TextDisplay("## __NO ACTIVE MAINTENANCE__\nEverything is running normally."))
        container.add_item(ui.Separator())
    else:
        name = (candidate.get("article_name") or "UPDATE").upper()
        unixes = candidate.get("article_unix") or [0, 0]
        u1 = unixes[0]
        u2 = unixes[1] if len(unixes) > 1 else u1

        is_data_update = "DATA UPDATE" in name
        in_progress = u1 <= now < u2

        if is_data_update:
            accent = 0x11d6d0
            title = f"## __{name}__\n### 📥 __DATA UPDATE NOTICE!__ 📥"
            body = (f"> All players will be kicked to home screen "
                    f"{'at ' if not relative else ''}{format_ts(u1, relative, 'f')} "
                    f"to download the update data.")
        elif in_progress:
            accent = 0xfc2803
            title = f"## __{name}__\n### 🔴 __MAINTENANCE IN PROGRESS!!__ 🚫"
            body = (f"> This maintenance started "
                    f"{'on ' if not relative else ''}{format_ts(u1, relative, 'f')}.\n\n"
                    f"### 🟢 **END OF MAINTENANCE**\n"
                    f"> If everything runs as planned, **service will be restored "
                    f"{'on ' if not relative else ''}{format_ts(u2, relative, 'f')}**.")
        else:
            accent = 0xfcd703
            title = f"## __{name}__\n### 🔴 __MAINTENANCE NOTICE!__ 🚫"
            body = (f"> The game will be offline "
                    f"{'on ' if not relative else ''}{format_ts(u1, relative, 'f')} "
                    f"for maintenance and will kick any logged player at that moment.\n\n"
                    f"🟢 **END OF MAINTENANCE**\n"
                    f"> Services will be restored "
                    f"{'on ' if not relative else ''}{format_ts(u2, relative, 'f')}, "
                    f"allowing users to download new data and log in.")

        container = ui.Container(accent_colour=accent)
        if candidate.get("article_logo"):
            gallery = ui.MediaGallery()
            gallery.add_item(media=candidate["article_logo"])
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(title))
        container.add_item(ui.TextDisplay(body))
        container.add_item(ui.Separator())

    # Botones
    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=discord.ButtonStyle.danger,
                           custom_id=f"schedule_update_{'rel' if relative else 'abs'}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_banner_{'rel' if relative else 'abs'}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_event_{'rel' if relative else 'abs'}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_maps_{'rel' if relative else 'abs'}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_misc_{'rel' if relative else 'abs'}", emoji="🏪"))
    container.add_item(row)

    # Toggle
    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_update_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)

    view.add_item(container)
    return view


def _build_gacha_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x8e24aa)

    container.add_item(ui.TextDisplay("## __CURRENT CALENDAR:__"))
    container.add_item(ui.Separator())

    news = load_json(NEWS_FILE, {})
    lines = []
    for art in news.values():
        if (art.get("article_type") or "").lower() != "gacha":
            continue
        name = (art.get("article_name") or "").upper()
        unixes = art.get("article_unix") or []
        if len(unixes) < 2:
            continue

        if "PAID-ONLY" in name:
            left = "PLACEHOLDER_REPLACE_gacha_paid_left"
            right = "PLACEHOLDER_REPLACE_gacha_paid_right"
        elif "[LIMITED]" in name or "LIMITED" in name:
            left = "PLACEHOLDER_REPLACE_gacha_limited_left"
            right = "PLACEHOLDER_REPLACE_gacha_limited_right"
        else:
            left = "PLACEHOLDER_REPLACE_gachatype_pickup_left"
            right = "PLACEHOLDER_REPLACE_gachatype_pickup_right"

        end_banner = unixes[1]
        end_exchange = unixes[2] if len(unixes) > 2 else None

        banner_txt = FlavorTextOnTime(
            end_banner,
            f"This banner leaves {format_ts(end_banner, relative, 'f')}.",
            "The banner is no longer available."
        )
        exchange_txt = "N/A"
        if end_exchange:
            exchange_txt = FlavorTextOnTime(
                end_exchange,
                f"The character leave the exchange {format_ts(end_exchange, relative, 'f')}.",
                "N/A"
            )

        clean = (name.replace("PAID-ONLY ★5 ", "")
                     .replace("[LIMITED] ", "")
                     .replace(" PICKUP", "")
                     .replace(" GACHA", "")
                     .replace(" RERUN", "")
                     .replace(" NOW AVAILABLE!", ""))

        block = (
            f"### {left}{right} **{clean}:**\n"
            f"-#  - PLACEHOLDER_REPLACE_time_remaining_for_gacha {banner_txt}\n"
            f"-#  - PLACEHOLDER_REPLACE_time_remaining_for_exchange {exchange_txt}"
        )
        lines.append(block)

    text = "\n\n".join(lines) if lines else "*No active gachas found.*"
    container.add_item(ui.TextDisplay(text))

    daily = GenerateUnixDay(0)
    container.add_item(ui.TextDisplay(
        f"ℹ️ The availability of banners and exchanges are updated at {format_ts(daily, False, 't')}."
    ))
    container.add_item(ui.Separator())

    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=discord.ButtonStyle.danger,
                           custom_id=f"schedule_update_{'rel' if relative else 'abs'}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=discord.ButtonStyle.success,
                           custom_id=f"schedule_banner_{'rel' if relative else 'abs'}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_event_{'rel' if relative else 'abs'}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_maps_{'rel' if relative else 'abs'}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_misc_{'rel' if relative else 'abs'}", emoji="🏪"))
    container.add_item(row)

    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_gacha_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)

    view.add_item(container)
    return view


def _build_event_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x43a047)

    container.add_item(ui.TextDisplay("## __CURRENT CALENDAR:__"))
    container.add_item(ui.Separator())

    news = load_json(NEWS_FILE, {})
    night = GenerateUnixDay(16)
    lines = []

    for art in news.values():
        if (art.get("article_type") or "").lower() != "event":
            continue
        name = (art.get("article_name") or "").upper()
        unixes = art.get("article_unix") or []
        if not unixes:
            continue

        max_ts = max(unixes)
        u1 = unixes[0]
        u2 = unixes[1] if len(unixes) > 1 else max_ts
        u3 = unixes[2] if len(unixes) > 2 else max_ts

        if "RAID BATTLE" in name:
            if name.startswith("[UPDATED]"):
                clean = name.replace("[UPDATED] ", "")
                block = (
                    f"### PLACEHOLDER_REPLACE_event_kaiju_raid **__{clean}__**\n"
                    f"> 📆 [__THREAT DEFEATED!__] The event ends {format_ts(max_ts, relative, 'd')}¹.\n"
                    f"- 📬 Ranking rewards should be sent on {format_ts(u1 + 172800, relative, 'd')}.\n"
                    f"- ⚠️ Unclaimed rewards will not be mailed."
                )
            else:
                block = (
                    f"### PLACEHOLDER_REPLACE_event_kaiju_raid **__{name}__**\n"
                    f"> ⚠️ [__THREAT IS ALIVE!__]\n"
                    f"- 🔁 You can claim x3 Free Battle Permits {format_ts(night, relative, 't')}.\n"
                    f"- ℹ️ *It's not possible to display the remaining life in real time.*"
                )
        elif "KAIJU RUSH" in name:
            rush_parts = []
            for i, ts in enumerate(unixes[1:5], 1):
                if ts > now_unix():
                    rush_parts.append(f"`{i}: ❌` {format_ts(ts, relative, 'd')}")
                else:
                    rush_parts.append(f"`{i}: ☑️`")
            rush_txt = ", ".join(rush_parts)
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_rush **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹.\n"
                f"- 🗓️ Area unlock dates: {rush_txt}"
            )
        elif "TOTAL WAR" in name:
            ticket_reset = max(unixes)
            playable = FlavorTextOnTime(
                u2,
                f"- 🎮 The event will be unplayable {format_ts(u2, relative, 'd')}.\n"
                f"- 🔁 The free event ticket resets {format_ts(ticket_reset, relative, 't')}.",
                "- 🔒 The event is no longer playable."
            )
            block = (
                f"### PLACEHOLDER_REPLACE_event_total_war **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u3, relative, 'd')}¹.\n"
                f"{playable}"
            )
        elif "BATTLE AREA (LIMITED)" in name:
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_arena **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹."
            )
        elif "MINI SPECIAL EVENT" in name or "SPECIAL EVENT" in name:
            unplayable = FlavorTextOnTime(
                u2,
                f"- 🎮 The event will be unplayable {format_ts(u2, relative, 'd')}.",
                "- 🔒 The event is no longer playable and you can only spend what you've earned."
            )
            block = (
                f"### PLACEHOLDER_REPLACE_event_special_event **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u3, relative, 'd')}¹.\n"
                f"{unplayable}"
            )
        elif "MOP-UP" in name:
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_mobup **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u1, relative, 'd')}¹.\n"
                f"- ℹ️ If there are 0 Kaiju remaining, the event will close automatically."
            )
        elif "MAIN STORY CH" in name:
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_chapter **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹."
            )
        elif "TRAINING:" in name:
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_training **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}².\n"
                f"- 🔁 This bonus applies to the first 10 clears and it's reset {format_ts(night, relative, 't')}."
            )
        elif "LARGE CONQUEST:" in name:
            block = (
                f"### PLACEHOLDER_REPLACE_event_kaiju_conquest **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹.\n"
                f"- ⚠️ Unclaimed rewards will not be mailed."
            )
        else:
            block = (
                f"### **__{name}__**\n"
                f"> 📆 Ends {format_ts(max_ts, relative, 'd')}."
            )
        lines.append(block)

    text = "\n\n".join(lines) if lines else "*No active events found.*"
    container.add_item(ui.TextDisplay(text))

    daily = GenerateUnixDay(0)
    night = GenerateUnixDay(16)
    container.add_item(ui.TextDisplay(
        f"ℹ️ Depending on the type of event, these are updated at "
        f"{format_ts(daily, False, 't')}¹ or {format_ts(night, False, 't')}²."
    ))
    container.add_item(ui.Separator())

    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=discord.ButtonStyle.danger,
                           custom_id=f"schedule_update_{'rel' if relative else 'abs'}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_banner_{'rel' if relative else 'abs'}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=discord.ButtonStyle.success,
                           custom_id=f"schedule_event_{'rel' if relative else 'abs'}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_maps_{'rel' if relative else 'abs'}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_misc_{'rel' if relative else 'abs'}", emoji="🏪"))
    container.add_item(row)

    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_event_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)

    view.add_item(container)
    return view


def _build_soon_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x03fcfc)

    container.add_item(ui.TextDisplay("## __UPCOMING CONTENT__"))

    img = get_best_roadmap_image()
    if img:
        gallery = ui.MediaGallery()
        gallery.add_item(media=img)
        container.add_item(gallery)
    else:
        container.add_item(ui.TextDisplay(
            "## __PEACE HAS RETURNED, THANKS TO EVERYONE!__\n"
            "Remember to keep up with your training and check the holiday schedule for your assigned division.\n"
            "- JAKDF"
        ))

    container.add_item(ui.Separator())

    upcoming = get_upcoming_events(3)
    if upcoming:
        lines = []
        for ts, text in upcoming:
            fmt = "R" if relative else "f"
            lines.append(f"<t:{ts}:{fmt}>\n{text}")
        container.add_item(ui.TextDisplay("\n\n".join(lines)))
    else:
        container.add_item(ui.TextDisplay("*No upcoming events found.*"))

    container.add_item(ui.Separator())

    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=discord.ButtonStyle.danger,
                           custom_id=f"schedule_update_{'rel' if relative else 'abs'}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_banner_{'rel' if relative else 'abs'}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_event_{'rel' if relative else 'abs'}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=discord.ButtonStyle.success,
                           custom_id=f"schedule_maps_{'rel' if relative else 'abs'}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_misc_{'rel' if relative else 'abs'}", emoji="🏪"))
    container.add_item(row)

    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_soon_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)

    view.add_item(container)
    return view


def _build_misc_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x546e7a)

    weekly = GenerateUnixWeek(7, 16)   # Domingo 16:00 JST
    monthly = GenerateUnixMonth(16)

    text = (
        f"## PLACEHOLDER_REPLACE_schedule_defense_force_pass __DEFENSE FORCE PASS:__\n"
        f"- 📅 The current season pass ends {format_ts(monthly, relative, 'f')}.\n"
        f"- 🚧 The weekly limit of 20,000 XP reset {format_ts(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_weekly_medal __IDENTIFIED KAIJU NEUTRALIZATION:__\n"
        f"- 🚧 The weekly limit of 5 medals resets {format_ts(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_store_stock __STORE - STOCKING:__\n"
        f"## > PLACEHOLDER_REPLACE_storetab_dce Restock {format_ts(weekly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_es Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_we Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_c Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_pov Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_eod Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_e Restock {format_ts(monthly, relative, 'd')}."
    )
    container.add_item(ui.TextDisplay(text))
    container.add_item(ui.Separator())

    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=discord.ButtonStyle.danger,
                           custom_id=f"schedule_update_{'rel' if relative else 'abs'}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_banner_{'rel' if relative else 'abs'}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_event_{'rel' if relative else 'abs'}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=discord.ButtonStyle.primary,
                           custom_id=f"schedule_maps_{'rel' if relative else 'abs'}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=discord.ButtonStyle.success,
                           custom_id=f"schedule_misc_{'rel' if relative else 'abs'}", emoji="🏪"))
    container.add_item(row)

    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_misc_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)

    view.add_item(container)
    return view


# ============================================================
#  COG PRINCIPAL
# ============================================================
class Calendar(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: Dict[str, ui.LayoutView] = {}
        self.default_key = "gacha_abs"
        self._public_cooldowns: Dict[int, float] = {}
        self.rebuild_calendar_cache()

    def rebuild_calendar_cache(self):
        """Se llama automáticamente después de cada escaneo."""
        log("[CALENDAR]: Rebuilding cache...", "calendar", show=False)

        self.cache["update_abs"] = _build_update_view(relative=False)
        self.cache["update_rel"] = _build_update_view(relative=True)

        self.cache["gacha_abs"]  = _build_gacha_view(relative=False)
        self.cache["gacha_rel"]  = _build_gacha_view(relative=True)

        self.cache["event_abs"]  = _build_event_view(relative=False)
        self.cache["event_rel"]  = _build_event_view(relative=True)

        self.cache["soon_abs"]   = _build_soon_view(relative=False)
        self.cache["soon_rel"]   = _build_soon_view(relative=True)

        self.cache["misc_abs"]   = _build_misc_view(relative=False)
        self.cache["misc_rel"]   = _build_misc_view(relative=True)

        # Página por defecto
        if self._has_active_maintenance():
            self.default_key = "update_abs"
        else:
            self.default_key = "gacha_abs"

        log(f"[CALENDAR]: Cache rebuilt → default: {self.default_key}", "calendar", show=False)

    def _has_active_maintenance(self) -> bool:
        news = load_json(NEWS_FILE, {})
        now = now_unix()
        for art in news.values():
            t = (art.get("article_type") or "").lower()
            if t in ("update", "maintenance"):
                unixes = art.get("article_unix") or []
                if unixes and max(unixes) > now:
                    return True
        return False

    # ----------------------------------------------------------
    #  COMANDO SLASH
    # ----------------------------------------------------------
    @app_commands.command(name="calendar", description="Tick-Tack! Don't miss the upcoming schedules...")
    @app_commands.describe(private="Reply privately (default: True)")
    async def calendar(self, interaction: discord.Interaction, private: bool = True):
        if not private:
            channel_id = interaction.channel_id
            now = time.time()
            if self._public_cooldowns.get(channel_id, 0) > now:
                await interaction.response.send_message(
                    "# OOPS!\nGlobal features have a cooldown system to avoid spam...",
                    ephemeral=True
                )
                return
            self._public_cooldowns[channel_id] = now + PUBLIC_COOLDOWN

        view = self.cache.get(self.default_key)
        if view is None:
            await interaction.response.send_message(
                "Calendar cache is empty. Please wait a moment while it rebuilds.",
                ephemeral=True
            )
            return

        await interaction.response.send_message(view=view, ephemeral=private)

    # ----------------------------------------------------------
    #  HANDLER DE BOTONES
    # ----------------------------------------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("schedule_"):
            return

        await interaction.response.defer()

        parts = custom_id.split("_")
        if len(parts) < 3:
            return

        action = parts[1]          # update / banner / event / maps / misc / toggle
        mode   = parts[2]          # abs / rel

        section_map = {
            "update": "update",
            "banner": "gacha",
            "event":  "event",
            "maps":   "soon",
            "misc":   "misc",
        }

        if action == "toggle":
            # schedule_toggle_SECTION_NEWMODE
            section = parts[2] if len(parts) > 3 else "gacha"
            new_mode = parts[3] if len(parts) > 3 else ("rel" if mode == "abs" else "abs")
            key = f"{section}_{new_mode}"
        else:
            section = section_map.get(action, "gacha")
            key = f"{section}_{mode}"

        view = self.cache.get(key) or self.cache.get(self.default_key)
        if view:
            await interaction.edit_original_response(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
    log("[COMMAND BUILDER]: /calendar", "slash", show=False)