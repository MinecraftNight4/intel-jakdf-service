import json
import os
import io
import math
from typing import Dict, Any, List, Optional, Tuple
from logger import info, warn, crit, log

import aiohttp
import discord
from discord import ui
from discord.ext import commands

# -------------------------------------------------
# Constantes
# -------------------------------------------------
FEED_ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF

NEWS_FILE   = "sys_save/request_news.json"
SETUP_FILE  = "sys_save/feed_system_setup.json"
DATA_FILE   = "sys_save/feed_system_data.json"

NAMESPACE = "feed_game_gacha"


# -------------------------------------------------
# Helpers de JSON
# -------------------------------------------------
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


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# -------------------------------------------------
# Descarga de imagen (persistente)
# -------------------------------------------------
async def download_image(url: str) -> Optional[Tuple[io.BytesIO, str]]:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                ext = url.split("?")[0].split(".")[-1].lower()
                if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
                    ext = "png"
                filename = f"feed_logo_{abs(hash(url)) % 100000}.{ext}"
                return io.BytesIO(data), filename
    except Exception as e:
        log(f"[ATTACHMENT]: Error downloading [{url}] due to: {e} ", "feed", level="CRIT", show=False)
        return None


# -------------------------------------------------
# Determinar el texto de fechas según criterios A / B / C
# -------------------------------------------------
def build_gacha_dates_text(article: dict) -> Optional[str]:
    """
    Devuelve el texto de fechas según A, B o C.
    Si no cumple ninguno → None (criterio D).
    """
    unix_list = article.get("article_unix") or []
    items = article.get("article_item") or []
    full_text = "\n".join(str(i) for i in items).lower()

    # Ordenamos de menor a mayor
    try:
        sorted_unix = sorted(int(u) for u in unix_list if u is not None)
    except (ValueError, TypeError):
        return None

    has_availability = "__availability period__" in full_text
    has_exchange = "exchange period" in full_text

    # A: 3 unix + exchange + availability
    if len(sorted_unix) == 3 and has_exchange and has_availability:
        s, m, b = sorted_unix
        return (
            f"- Released on <t:{s}:f> (<t:{s}:R>)\n"
            f"- Gacha ends on <t:{m}:f> (<t:{m}:R>)\n"
            f"- Exchange ends on <t:{b}:f> (<t:{b}:R>)"
        )

    # B: 3 unix + NO exchange + availability
    if len(sorted_unix) == 3 and not has_exchange and has_availability:
        s, m, b = sorted_unix
        return (
            f"- Released on <t:{s}:f> (<t:{s}:R>)\n"
            f"- Event ends on <t:{m}:f> (<t:{m}:R>)\n"
            f"- Gacha ends on <t:{b}:f> (<t:{b}:R>)"
        )

    # C: 2 unix + availability
    if len(sorted_unix) == 2 and has_availability:
        s, b = sorted_unix
        return (
            f"- Released on <t:{s}:f> (<t:{s}:R>)\n"
            f"- Gacha ends on <t:{b}:f> (<t:{b}:R>)"
        )

    # D → no construir embed
    return None


# -------------------------------------------------
# Vista del feed de gacha (banner + título + fechas + botones)
# -------------------------------------------------
class FeedGachaPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        dates_text: str,
        logo_media: str | None = None,
    ):
        super().__init__()

        uuid = article["article_uuid"]

        rgb_hex = article.get("article_rgbs", "ffffff")
        try:
            accent = int(rgb_hex, 16)
        except (ValueError, TypeError):
            accent = ACCENT_COLOR

        container = ui.Container(accent_colour=accent)

        # BANNER (permanente vía attachment si está disponible)
        final_logo = logo_media or article.get("article_logo")
        if final_logo:
            gallery = ui.MediaGallery()
            gallery.add_item(media=final_logo)
            container.add_item(gallery)

        # Título + URL + hora de publicación
        header = (
            f"# __{article['article_name']}__\n"
            f"[`🔗`](https://info.kj8-thegame.com/news/{uuid}"
            f"?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) "
            f"Posted on <t:{article['article_time']}:f>."
        )
        container.add_item(ui.TextDisplay(header))
        container.add_item(ui.Separator())

        # TEXTO de fechas (A / B / C)
        container.add_item(ui.TextDisplay(dates_text))
        container.add_item(ui.Separator())

        # BOTONES (mismos custom_id que el sistema de news para que funcionen)
        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="private_gamenews_menu"
        ))
        row.add_item(ui.Button(
            label="READ MORE",
            emoji="ℹ️",
            style=discord.ButtonStyle.primary,
            custom_id=f"private_gamenews_{uuid}_1"
        ))

        container.add_item(row)
        self.add_item(container)


# -------------------------------------------------
# Lógica principal de feeds – solo gacha
# -------------------------------------------------
async def process_feed_game_gacha(bot: commands.Bot) -> int:
    news: Dict[str, Any] = load_json(NEWS_FILE, {})
    setup = load_json(SETUP_FILE, {})
    data  = load_json(DATA_FILE, {})

    if NAMESPACE not in data:
        data[NAMESPACE] = []

    already_sent = set(data[NAMESPACE])
    feed_channels = setup.get(NAMESPACE, {})

    if not feed_channels:
        log(f"[FEED]: The category '{NAMESPACE}' is empty!", "news", show=False)
        return 0

    # 1. Hashes actuales del scrape (solo tipo gacha)
    current_hashes = set()
    articles_by_hash = {}

    for article in news.values():
        if (article.get("article_type") or "").lower() != "gacha":
            continue

        h = article.get("article_hash")
        if h and h != "0":
            current_hashes.add(h)
            articles_by_hash[h] = article

    # 2. Hashes nuevos
    new_hashes = current_hashes - already_sent

    if not new_hashes:
        data[NAMESPACE] = list(current_hashes)
        save_json(DATA_FILE, data)
        log(f"[GACHA]: No new articles available!", "news", level="WARN", show=False)
        return 0

    # Ordenar nuevas por fecha (más recientes primero)
    new_articles = sorted(
        (articles_by_hash[h] for h in new_hashes),
        key=lambda a: int(a.get("article_time", 0)),
        reverse=True
    )

    new_count = 0

    # -------------------------------------------------
    # Publicar en cada canal configurado
    # -------------------------------------------------
    for guild_id, entry in feed_channels.items():
        channel_id = entry.get("channel")
        if not channel_id:
            continue

        channel = bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except Exception:
                log(f"[FEED]: The channel {channel_id} is unreachable!", "news", level="CRIT", show=False)
                continue

        can_publish = bool(entry.get("publish", False))
        is_announcement = getattr(channel, "is_news", lambda: False)()

        for article in new_articles:
            # Criterios A / B / C
            dates_text = build_gacha_dates_text(article)

            if dates_text is None:
                # Criterio D → no construir embed, pero marcar como procesado
                log(f"[GACHA]: Skipped (no A/B/C) → {article.get('article_name', '')[:50]}", "news", show=False)
                continue

            files: List[discord.File] = []
            logo_media = None
            logo_url = article.get("article_logo")

            if logo_url:
                result = await download_image(logo_url)
                if result:
                    file_data, filename = result
                    files.append(discord.File(file_data, filename=filename))
                    logo_media = f"attachment://{filename}"

            view = FeedGachaPageView(
                article,
                dates_text=dates_text,
                logo_media=logo_media
            )

            try:
                for f in files:
                    f.fp.seek(0)

                msg = await channel.send(
                    view=view,
                    files=files if files else None
                )
                log(f"[POSTING GACHA]: {article.get('article_name')[:50]} → #{getattr(channel, 'name', channel_id)}", "news", show=False)

                if can_publish and is_announcement:
                    try:
                        await msg.publish()
                        log(f"- CROSSPOSTED: True", "news", show=False)
                    except Exception as e:
                        log(f"- CROSSPOSTED: False | {e}", "news", level="CRIT", show=False)

            except Exception as e:
                log(f"[POSTING]: COMMUNICATION ERROR AT {channel_id} | {e}", "news", level="CRIT", show=False)

            new_count += 1

        # Mensaje de ping (después de todas las noticias de este canal)
        ping_text = entry.get("text")
        if ping_text and str(ping_text).strip():
            try:
                await channel.send(content=str(ping_text).strip())
                log(f"[POSTING]: This ping message was sent to #{getattr(channel, 'name', channel_id)}!", "news", show=False)
            except Exception as e:
                log(f"[POSTING]: This ping message was not dispatched at {channel_id} | {e}", "news", level="CRIT", show=False)

    # 3. Guardar TODOS los hashes actuales (incluye los de criterio D)
    data[NAMESPACE] = list(current_hashes)
    save_json(DATA_FILE, data)
    log(f"[POSTING GACHA]: A total of x{new_count} articles sent!", "news", show=False)
    return new_count