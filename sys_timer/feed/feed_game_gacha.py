import os
import io
import math
import json
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from logger import info, warn, crit, log

import aiohttp
import discord
from discord import ui
from discord.ext import commands

# -------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------- 
FEED_ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF

NEWS_FILE   = "sys_save/request_news.json"
SETUP_FILE  = "sys_save/feed_system_setup.json"
DATA_FILE   = "sys_save/feed_system_data.json"

NAMESPACE = "feed_game_gacha"


# -------------------------------------------------
# BASE DE DATOS
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
# DESCARGA DE ELEMENTOS WEB A FORMATO PERMANENTE
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
def build_gacha_info_text(article: dict) -> Optional[str]:
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
# GENERADOR DE EMBED
# ------------------------------------------------- 
class FeedGachaPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        info_text: str,
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
        container.add_item(ui.TextDisplay(info_text))
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
    
    channel_count = len(feed_channels)
    gacha_articles = [
        a for a in news.values()
        if (a.get("article_type") or "").lower() == "gacha"
        and a.get("article_hash") and a.get("article_hash") != "0"
    ]
    article_count = len(gacha_articles)

    log(f"[FEED - GACHA]: [CHANNELS: x{channel_count}] [ARTICLES: x{article_count}]", "feed", show=False)

    # -------------------------------------------------
    # 3) Sin canales → salir temprano
    # -------------------------------------------------
    if channel_count == 0:
        log(f"[FEED - GACHA]: [ERROR: NO CHANNELS] ", "feed", level="WARN", show=False)
        log(f"[FEED - GACHA]: Thread closed.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0

    current_hashes = set()
    articles_by_hash = {}

    for article in gacha_articles:
        h = article.get("article_hash")
        current_hashes.add(h)
        articles_by_hash[h] = article

    new_hashes = current_hashes - already_sent
    if not new_hashes:
        data[NAMESPACE] = list(current_hashes)
        save_json(DATA_FILE, data)
        log(f"[FEED - GACHA]: [ERROR: NO ARTICLES] ", "feed", level="WARN", show=False)
        log(f"[FEED - GACHA]: Thread closed.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0

    
    new_articles = [articles_by_hash[h] for h in new_hashes]
    new_count = 0

    log(f"[FEED - GACHA]: [ARTICLES: x{len(new_articles)}]", "feed", show=False)



    # -------------------------------------------------
    # Publicar en cada canal configurado
    # -------------------------------------------------
    log(f"[FEED - GACHA]: SENDING ARTICLES... ", "feed", show=False)
    for guild_id, entry in feed_channels.items():
        channel_id = entry.get("channel")
        if not channel_id:
            continue
        
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except Exception:
                log(f"- [{channel_id}]: FAILURE", "feed", level="CRIT", show=False)
                continue
        
        log(f"- [{channel_id}]: SUCCESS", "feed", show=False)
        can_publish = bool(entry.get("publish", False))
        is_announcement = getattr(channel, "is_news", lambda: False)()
        for article in new_articles:
            info_text = build_gacha_info_text(article)

            if info_text is None:
                log(f"  - [ERROR: NO FORMAT] - [HASH: {article.get('article_hash')}] {article.get('article_name')}", "feed", level="WARN", show=False)
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

            view = FeedGachaPageView(article, info_text=info_text, logo_media=logo_media)
            await asyncio.sleep(2)
            try:
                for f in files:
                    f.fp.seek(0)
                msg = await asyncio.wait_for(channel.send(view=view, files=files if files else None), timeout=10.0)
                log(f"  - [SEND: SUCCESS] | HASH: {article.get('article_hash')} | {article.get('article_name')}", "feed", show=False)
                if can_publish and is_announcement:
                    await asyncio.sleep(2)
                    try:
                        await asyncio.wait_for(msg.publish(), timeout=5.0)
                        log(f"      ⤷ CROSSPOST: [SENT: SUCCESS]", "feed", show=False)
                    except Exception as e:
                        log(f"      ⤷ CROSSPOST: [SENT: FAILURE] | {e}", "feed", level="WARN", show=False)
                        continue

            except Exception as e:
                log(f"  - [SEND: FAILURE] | HASH: {article.get('article_hash')} | {article.get('article_name')} | {e}", "feed", level="CRIT", show=False)
                continue
            new_count += 1


        ping_text = entry.get("text")
        if ping_text and str(ping_text).strip():
            await asyncio.sleep(2)
            try:
                await asyncio.wait_for(channel.send(content=str(ping_text).strip()), timeout=5.0)
                log(f"    ⤷ PING: [SENT: SUCCESS] | {ping_text} ", "feed", show=False)
            except Exception as e:
                log(f"    ⤷ PING: [SENT: FAILURE] | {e} ", "feed", level="CRIT", show=False)
                continue
        if ping_text is None:
            log(f"    ⤷ PING: [SENT: SKIPPED]", "feed", show=False)

    data[NAMESPACE] = list(current_hashes)
    save_json(DATA_FILE, data)

    log(f"[FEED - GACHA]: [SENT x{new_count}]", "feed", show=False)
    log(f"[FEED - GACHA]: Thread closed.", "feed", show=False)
    log(f" ", "feed", show=False)
    return new_count