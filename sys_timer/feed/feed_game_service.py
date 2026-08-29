import os
import io
import math
import json
import aiohttp
import discord
import asyncio


from typing import Dict, Any, List, Optional, Tuple
from logger import info, warn, crit, log
from discord.ext import commands
from discord import ui

# -------------------------------------------------
# CONFIGURACIÓN
# ------------------------------------------------- 
FEED_ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF

NEWS_FILE   = "sys_save/request_news.json"
SETUP_FILE  = "sys_save/feed_system_setup.json"
DATA_FILE   = "sys_save/feed_system_data.json"

NAMESPACE = "feed_game_update"


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
# GENERADOR DE EMBED
# ------------------------------------------------- 
class FeedNewsPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        item_max: int = FEED_ITEMS_PER_PAGE,
        item_ico: str | None = None,
    ):
        super().__init__()

        # VARIABLE SETUP
        article_uuid = article["article_uuid"]
        article_node = article.get("article_node", [])
        article_item = article.get("article_item", [])
        article_rgbs = int(article.get("article_rgbs", "ffffff"), 16)
        article_logo = item_ico or article.get("article_logo")
        
        math_item = len(article_node)
        math_page = max(1, math.ceil(math_item / item_max))
        
        page_item = article_item[:item_max]
        page_node = article_node[:item_max]
        
        
        # EMBED
        container = ui.Container(accent_colour=article_rgbs)

        # EMBED - HEADER
        if article_logo:
            gallery = ui.MediaGallery()
            gallery.add_item(media=article_logo)
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(f"# __{article['article_name']}__\n [`🔗`](https://info.kj8-thegame.com/news/{article_uuid}?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) Posted on <t:{article['article_time']}>."))
        container.add_item(ui.Separator())
        
        # EMBED - NEWS BODY
        text_storage: list[str] = []
        
        def flush_text():
            if text_storage:
                cleaned = [t.strip() for t in text_storage if t.strip()]
                if cleaned:
                    container.add_item(ui.TextDisplay("\n".join(cleaned)))
                text_storage.clear()
        
        for item_type, item_read in zip(page_node, page_item):
            if item_type == "txt":
                text_storage.append(item_read)
            elif item_type == "img":
                flush_text()
                gal = ui.MediaGallery()
                gal.add_item(media=item_read)
                container.add_item(gal)
            else:
                # HOW, HOOOW!?
                text_storage.append(f"**{item_type}**\n{item_read}")
        flush_text()
        container.add_item(ui.Separator())
        
        # EMBED - BUTTONS
        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="private_gamenews_menu"
        ))
        row.add_item(ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{article_uuid}_0",
            disabled=True
        ))
        row.add_item(ui.Button(
            label=f"PAGE 1 OF {math_page}",
            style=discord.ButtonStyle.success,
            custom_id=f"private_gamenews_{article_uuid}_index_1",
            disabled=1 >= math_page
        ))
        row.add_item(ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{article_uuid}_2",
            disabled=1 >= math_page
        ))
        container.add_item(row)
        self.add_item(container)


# -------------------------------------------------
# Lógica principal – solo events
# -------------------------------------------------
async def process_feed_game_service(bot: commands.Bot) -> int:
    storage_data = load_json(DATA_FILE, {})
    storage_sent = load_json(DATA_FILE, {}).get(NAMESPACE, []) or []
    storage_feed = load_json(SETUP_FILE, {}).get(NAMESPACE, {}) or []
    storage_news: Dict[str, Any] = load_json(NEWS_FILE, {})


    #=================#
    # PROCESS OF DATA #
    #=================#
    process_sent = set(storage_sent)
    process_news = [
        read for read in storage_news.values()
        if (read.get("article_type") or "").lower() == ("update" or "maintenance")
        and read.get("article_hash")
    ]
    index_article_hash = set()
    index_article_data = {}
    #
    for item in process_news:
        hash = item.get("article_hash")
        index_article_hash.add(hash)
        index_article_data[hash] = item
    process_list = index_article_hash - process_sent
    process_post = [index_article_data[h] for h in process_list]
    #
    debug_all_feed = len(storage_feed)
    debug_can_post = len(process_list)
    debug_all_post = len(storage_news)
    log(f"[FEED - SERVICE]: [CHANNELS: {debug_all_feed}] [ARTICLES: {debug_can_post}/{debug_all_post}]", "feed", show=False)


    #==============#
    # CLOSE THREAD #
    #==============#
    if (len(storage_feed) == 0) or (not process_list):
        storage_data[NAMESPACE] = list(index_article_hash)
        save_json(DATA_FILE, storage_data)        
        log(f"[FEED - SERVICE]: THREAD CLOSED.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0
    
    
    #==================#
    # MESSAGE DELIVERY #
    #==================#
    log(f"[FEED - SERVICE]: SENDING ARTICLES... ", "feed", show=False)
    debug_post_sent = 0
    for guild_uuid, guild_data in storage_feed.items():


        feed_data_hold = bot.get_channel(int(guild_data.get("channel")))
        if feed_data_hold is None:
            try:
                feed_data_hold = await bot.fetch_channel(int(guild_data.get("channel")))
            except Exception:
                log(f"- [ID: {guild_data.get("channel")}] [FAILURE: True]", "feed", level="CRIT", show=False)
                continue
        feed_data_post = getattr(feed_data_hold, "is_news", lambda: False)()
        feed_data_rule = bool(guild_data.get("publish", False))
        log(f"- [ID: {guild_data.get("channel")}] | [IS_NEWS: {feed_data_post}] | [PUBLISH: {feed_data_rule}]", "feed", show=False)


        for item in process_post:
            message_file: List[discord.File] = []
            message_icon = None
            if item.get("article_logo"):
                message_save = await download_image(item.get("article_logo"))
                if message_save:
                    result_data, result_name = message_save
                    result_data.seek(0)
                    message_file.append(discord.File(result_data, filename=result_name))
                    message_icon = f"attachment://{result_name}"


            await asyncio.sleep(2)
            message_data = FeedNewsPageView(item, item_ico=message_icon, item_max=FEED_ITEMS_PER_PAGE)
            try:
                for file_item in message_file:
                    file_item.fp.seek(0)
                message_sent = await asyncio.wait_for(feed_data_hold.send(view=message_data, files=message_file if message_file else None), timeout=10.0)
                log(f"  - [SEND: SUCCESS] | HASH: {item.get('article_hash')} | {item.get('article_name')}", "feed", show=False)


                if feed_data_post and feed_data_rule:
                    await asyncio.sleep(2)
                    try:
                        await asyncio.wait_for(message_sent.publish(), timeout=5.0)
                        log(f"        ⤷ CROSSPOST: SUCCESS", "feed", show=False)
                    except Exception as e:
                        log(f"        ⤷ [(!) FAILURE] #ERROR_FLAG_0001 | #{item.get('article_hash')}] - {item.get('article_name')} | DUMP: {e}", "feed", level="CRIT", show=False)
                        continue
            except Exception as e:
                log(f"  - [(!) FAILURE] #ERROR_FLAG_0002 | #{item.get('article_hash')}] - {item.get('article_name')} | DUMP: {e}", "feed", level="CRIT", show=False)
                continue
            debug_post_sent += 1


        feed_ping_text = guild_data.get("text")
        if feed_ping_text and str(feed_ping_text).strip():
            await asyncio.sleep(2)
            try:
                await asyncio.wait_for(feed_data_hold.send(content=str(feed_ping_text).strip()), timeout=5.0)
                log(f"    ⤷ PING: SUCCESS", "feed", show=False)
            except Exception as e:
                log(f"    ⤷ [(!) FAILURE] #ERROR_FLAG_0003 | DUMP: {e} ", "feed", level="CRIT", show=False)
                continue


    storage_data[NAMESPACE] = list(index_article_hash)
    save_json(DATA_FILE, storage_data)
    log(f"[FEED - SERVICE]: [SENT: {debug_post_sent}]", "feed", show=False)
    log(f"[FEED - SERVICE]: THREAD CLOSED.", "feed", show=False)
    log(f" ", "feed", show=False)
    return debug_post_sent
