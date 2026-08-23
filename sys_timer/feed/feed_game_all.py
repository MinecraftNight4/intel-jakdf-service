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
# Vista del feed (solo 1ª página + botones privados)
# -------------------------------------------------
class FeedNewsPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        items_per_page: int = FEED_ITEMS_PER_PAGE,
        logo_media: str | None = None,
    ):
        super().__init__()

        uuid = article["article_uuid"]
        nodes = article.get("article_node", [])
        items = article.get("article_item", [])
        total_items = len(nodes)
        total_pages = max(1, math.ceil(total_items / items_per_page)) if total_items else 1

        page_nodes = nodes[:items_per_page]
        page_items = items[:items_per_page]

        rgb_hex = article.get("article_rgbs", "ffffff")
        try:
            accent = int(rgb_hex, 16)
        except (ValueError, TypeError):
            accent = ACCENT_COLOR

        container = ui.Container(accent_colour=accent)

        final_logo = logo_media or article.get("article_logo")
        if final_logo:
            gallery = ui.MediaGallery()
            gallery.add_item(media=final_logo)
            container.add_item(gallery)

        header = (
            f"# __{article['article_name']}__\n"
            f"[`🔗`](https://info.kj8-thegame.com/news/{uuid}"
            f"?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) "
            f"Posted on <t:{article['article_time']}>."
        )
        container.add_item(ui.TextDisplay(header))
        container.add_item(ui.Separator())

        current_text: list[str] = []

        def flush_text():
            if current_text:
                cleaned = [t.strip() for t in current_text if t.strip()]
                if cleaned:
                    container.add_item(ui.TextDisplay("\n".join(cleaned)))
                current_text.clear()

        for node_type, content in zip(page_nodes, page_items):
            if node_type == "txt":
                current_text.append(content)
            elif node_type == "img":
                flush_text()
                gal = ui.MediaGallery()
                gal.add_item(media=content)
                container.add_item(gal)
            else:
                current_text.append(f"**{node_type}**\n{content}")

        flush_text()

        if len(container.children) <= (2 if final_logo else 1):
            container.add_item(ui.TextDisplay("*`error_missing_text`*"))

        container.add_item(ui.Separator())

        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="private_gamenews_menu"
        ))
        row.add_item(ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{uuid}_0",
            disabled=True
        ))
        row.add_item(ui.Button(
            label=f"PAGE 1 OF {total_pages}",
            style=discord.ButtonStyle.success,
            custom_id=f"private_gamenews_{uuid}_index_1",
            disabled=total_pages <= 1
        ))

        next_disabled = total_items <= items_per_page or total_pages <= 1
        row.add_item(ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{uuid}_2",
            disabled=next_disabled
        ))

        container.add_item(row)
        self.add_item(container)


# -------------------------------------------------
# Lógica principal de feeds
# -------------------------------------------------
async def process_feed_game_all(bot: commands.Bot) -> int:
    news: Dict[str, Any] = load_json(NEWS_FILE, {})
    setup = load_json(SETUP_FILE, {})
    data  = load_json(DATA_FILE, {})

    if "feed_game_all" not in data:
        data["feed_game_all"] = []

    already_sent = set(data["feed_game_all"])
    feed_channels = setup.get("feed_game_all", {})

    if not feed_channels:
        log(f"[FEED - ALL]: [ERROR: NO CHANNELS] ", "feed", level="WARN", show=False)
        log(f"[FEED - ALL]: Thread closed.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0

    # 1. Hashes actuales del scrape
    current_hashes = set()
    articles_by_hash = {}

    for article in news.values():
        h = article.get("article_hash")
        if h and h != "0":
            current_hashes.add(h)
            articles_by_hash[h] = article

    # 2. Hashes nuevos
    new_hashes = current_hashes - already_sent

    if not new_hashes:
        data["feed_game_all"] = list(current_hashes)
        save_json(DATA_FILE, data)
        log(f"[FEED - ALL]: [ERROR: NO ARTICLES] ", "feed", level="WARN", show=False)
        log(f"[FEED - ALL]: Thread closed.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0

    new_articles = sorted(
        (articles_by_hash[h] for h in new_hashes),
        key=lambda a: int(a.get("article_time", 0)),
        reverse=True)

    new_count = 0

    # -------------------------------------------------
    # Publicar en cada canal configurado
    # -------------------------------------------------
    log(f"[FEED - ALL]: SENDING ARTICLES... ", "feed", show=False)
    for guild_id, entry in feed_channels.items():
        channel_id = entry.get("channel")
        if not channel_id:
            continue

        # Obtener canal
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

        # ----- Enviar cada noticia nueva -----
        for article in new_articles:
            files: List[discord.File] = []
            logo_media = None
            logo_url = article.get("article_logo")

            if logo_url:
                result = await download_image(logo_url)
                if result:
                    file_data, filename = result
                    files.append(discord.File(file_data, filename=filename))
                    logo_media = f"attachment://{filename}"

            view = FeedNewsPageView(article, items_per_page=FEED_ITEMS_PER_PAGE, logo_media=logo_media)

            try:
                for f in files:
                    f.fp.seek(0)

                msg = await channel.send(view=view, files=files if files else None)
                log(f"  - [SEND: SUCCESS] | HASH: {article.get('article_hash')} | {article.get('article_name')}", "feed", show=False)
                
                if can_publish and is_announcement:
                    try:
                        await msg.publish()
                        log(f"      ⤷ CROSSPOST: [SENT: SUCCESS]", "feed", show=False)
                    except Exception as e:
                        log(f"      ⤷ CROSSPOST: [SENT: FAILURE] | {e}", "feed", level="WARN", show=False)

            except Exception as e:
                log(f"  - [SEND: FAILURE] | HASH: {article.get('article_hash')} | {article.get('article_name')} | {e}", "feed", level="CRIT", show=False)
            new_count += 1

        ping_text = entry.get("text")
        if ping_text and str(ping_text).strip():
            try:
                await channel.send(content=str(ping_text).strip())
                log(f"    ⤷ PING: [SENT: SUCCESS] | {ping_text} ", "feed", show=False)
            except Exception as e:
                log(f"    ⤷ PING: [SENT: FAILURE] | {e} ", "feed", level="CRIT", show=False)
        if ping_text is None:
            log(f"    ⤷ PING: [SENT: SKIPPED]", "feed", show=False)
                

    data["feed_game_all"] = list(current_hashes)
    save_json(DATA_FILE, data)
    
    log(f"[FEED - ALL]: [SENT x{new_count}]", "feed", show=False)
    log(f"[FEED - ALL]: Thread closed.", "feed", show=False)
    log(f" ", "feed", show=False)
    return new_count