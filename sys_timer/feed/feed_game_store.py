import os
import io
import json
import hashlib
import aiohttp
import discord
import asyncio


from typing import Dict, Any, List, Optional, Tuple
from logger import log
from discord.ext import commands
from discord import ui

# -------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------
ACCENT_FALLBACK = 0x5865F2
STORE_URL = "https://webstore.kj8-thegame.com/?language=en"

SALE_FILE  = "sys_save/request_sale.json"
SETUP_FILE = "sys_save/feed_system_setup.json"
DATA_FILE  = "sys_save/feed_system_data.json"

NAMESPACE = "feed_game_store"


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


def color_from_sku(sku: str) -> int:
    """Stable accent colour derived from the item SKU."""
    digest = hashlib.sha256(sku.encode("utf-8")).digest()
    red = 48 + digest[0] % 208
    green = 48 + digest[1] % 208
    blue = 48 + digest[2] % 208
    return (red << 16) | (green << 8) | blue


def commit_hashes(previous: list, current: list, catalog_size: int, replace: bool) -> list:
    """Same rule as the in-game news feeds.

    Nothing to send (or nobody subscribed): keep only hashes still in the
    catalog, so removed offers don't stay forever.
    After a send: union the previous list with the current catalog, then if
    that exceeds the catalog size drop the oldest entries.
    Current hashes are appended last so the trim never forgets a live offer
    while a dead one is still sitting in the list.
    """
    current_clean = []
    seen = set()
    for raw in current:
        if isinstance(raw, str) and raw and raw not in seen:
            seen.add(raw)
            current_clean.append(raw)

    if replace:
        return current_clean

    merged = []
    seen = set()
    for raw in list(previous) + current_clean:
        if not isinstance(raw, str) or not raw or raw in seen:
            continue
        seen.add(raw)
        merged.append(raw)

    if catalog_size >= 0 and len(merged) > catalog_size:
        merged = merged[-catalog_size:]
    return merged


def write_notification(hashes: list) -> None:
    """Persiste los hashes de notificación en feed_system_data.json (NAMESPACE)."""
    data = load_json(DATA_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data[NAMESPACE] = hashes
    save_json(DATA_FILE, data)


# -------------------------------------------------
# DESCARGA DE ELEMENTOS WEB A FORMATO PERMANENTE
# -------------------------------------------------
async def download_image(url: str) -> Optional[Tuple[bytes, str]]:
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
                filename = f"store_logo_{abs(hash(url)) % 100000}.{ext}"
                return data, filename
    except Exception as e:
        log(f"[ATTACHMENT]: Error downloading [{url}] due to: {e} ", "feed", level="CRIT", show=False)
        return None


# -------------------------------------------------
# GENERADOR DE EMBED
# -------------------------------------------------
class FeedStoreItemView(ui.LayoutView):
    def __init__(self, sku: str, item: dict, banner: str | None):
        super().__init__()

        try:
            accent = color_from_sku(str(sku))
        except Exception:
            accent = ACCENT_FALLBACK

        container = ui.Container(accent_colour=accent)

        # ATTACHMENT — service-last_logo
        if banner:
            gallery = ui.MediaGallery()
            gallery.add_item(media=banner)
            container.add_item(gallery)

        container.add_item(ui.Separator())

        text = item.get("text_entry")
        if not isinstance(text, str) or not text.strip():
            text = f"### {item.get('name') or sku}"
        text = text.strip()
        if len(text) > 4000:
            text = text[:3990].rstrip() + "\n…"

        icon = item.get("icon")
        if isinstance(icon, str) and icon.startswith(("http://", "https://")):
            name = item.get("name") if isinstance(item.get("name"), str) else str(sku)
            container.add_item(ui.Section(
                ui.TextDisplay(text),
                accessory=ui.Thumbnail(icon, description=name[:256]),
            ))
        else:
            container.add_item(ui.TextDisplay(text))

        container.add_item(ui.Separator())

        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="Webstore",
            style=discord.ButtonStyle.link,
            url=STORE_URL,
        ))
        container.add_item(row)
        self.add_item(container)


# -------------------------------------------------
# Lógica principal – tienda
# -------------------------------------------------
async def process_feed_game_store(bot: commands.Bot, progress=None, progress_key: str = None) -> int:
    sale: Dict[str, Any] = load_json(SALE_FILE, {})
    if not isinstance(sale, dict):
        sale = {}

    item_data = sale.get("item_data") or {}
    if not isinstance(item_data, dict):
        item_data = {}

    # Hashes de notificación ahora viven en feed_system_data.json
    storage_data = load_json(DATA_FILE, {})
    if not isinstance(storage_data, dict):
        storage_data = {}
    notified = storage_data.get(NAMESPACE) or []
    if not isinstance(notified, list):
        notified = []

    storage_feed = load_json(SETUP_FILE, {}).get(NAMESPACE) or {}
    if not isinstance(storage_feed, dict):
        storage_feed = {}

    banner_url = sale.get("service-last_logo")
    if not isinstance(banner_url, str):
        banner_url = None


    #=================#
    # PROCESS OF DATA #
    #=================#
    process_sent = {h for h in notified if isinstance(h, str) and h}
    current_ordered: List[str] = []
    seen = set()
    process_post: List[tuple] = []

    for sku, item in item_data.items():
        if not isinstance(item, dict):
            continue
        item_hash = item.get("hash")
        if not isinstance(item_hash, str) or not item_hash:
            continue
        if item_hash not in seen:
            seen.add(item_hash)
            current_ordered.append(item_hash)
        if item_hash not in process_sent:
            process_post.append((str(sku), item, item_hash))

    index_article_hash = set(current_ordered)

    eta_work_total = len(process_post) * max(len(storage_feed), 1)
    eta_work_write = 0
    if progress and progress_key and eta_work_total > 0:
        progress.update_progress(progress_key, 0, eta_work_total)

    debug_all_feed = len(storage_feed)
    debug_can_post = len(process_post)
    debug_all_post = len(item_data)
    log(f"[FEED - STORE]: [CHANNELS: {debug_all_feed}] [ARTICLES: {debug_can_post}/{debug_all_post}]", "feed", show=False)


    #==============#
    # CLOSE THREAD #
    #==============#
    if len(storage_feed) == 0 or not process_post:
        write_notification(commit_hashes(notified, current_ordered, len(item_data), replace=True))
        log(f"[FEED - STORE]: THREAD CLOSED.", "feed", show=False)
        log(f"", "feed", show=False)
        return 0


    #==================#
    # MESSAGE DELIVERY #
    #==================#
    log(f"[FEED - STORE]: SENDING ARTICLES... ", "feed", show=False)
    banner_bytes = None
    banner_name = None
    if banner_url:
        downloaded = await download_image(banner_url)
        if downloaded:
            banner_bytes, banner_name = downloaded

    debug_post_sent = 0
    for guild_uuid, guild_data in storage_feed.items():
        if not isinstance(guild_data, dict):
            continue

        channel_id = guild_data.get("channel")
        try:
            feed_data_hold = bot.get_channel(int(channel_id))
        except (TypeError, ValueError):
            log(f"- [ID: {channel_id}] [FAILURE: True]", "feed", level="CRIT", show=False)
            continue

        if feed_data_hold is None:
            try:
                feed_data_hold = await bot.fetch_channel(int(channel_id))
            except Exception:
                log(f"- [ID: {channel_id}] [FAILURE: True]", "feed", level="CRIT", show=False)
                continue

        feed_data_post = getattr(feed_data_hold, "is_news", lambda: False)()
        feed_data_rule = bool(guild_data.get("publish", False))
        log(f"- [ID: {channel_id}] | [IS_NEWS: {feed_data_post}] | [PUBLISH: {feed_data_rule}]", "feed", show=False)

        for sku, item, item_hash in process_post:
            message_file: List[discord.File] = []
            message_icon = None
            if banner_bytes and banner_name:
                message_file.append(discord.File(io.BytesIO(banner_bytes), filename=banner_name))
                message_icon = f"attachment://{banner_name}"

            await asyncio.sleep(2)
            message_data = FeedStoreItemView(sku, item, banner=message_icon)
            try:
                for file_item in message_file:
                    file_item.fp.seek(0)
                message_sent = await asyncio.wait_for(
                    feed_data_hold.send(view=message_data, files=message_file if message_file else None),
                    timeout=20.0,
                )
                log(f"  - [SEND: SUCCESS] | HASH: {item_hash} | {item.get('name')}", "feed", show=False)

                if feed_data_post and feed_data_rule:
                    await asyncio.sleep(2)
                    try:
                        await asyncio.wait_for(message_sent.publish(), timeout=5.0)
                        log(f"        ⤷ CROSSPOST: SUCCESS", "feed", show=False)
                    except Exception as e:
                        log(f"        ⤷ [(!) FAILURE] #ERROR_FLAG_0001 | #{item_hash}] - {item.get('name')} | DUMP: {e}", "feed", level="CRIT", show=False)
                        continue
            except Exception as e:
                log(f"  - [(!) FAILURE] #ERROR_FLAG_0002 | #{item_hash}] - {item.get('name')} | DUMP: {e}", "feed", level="CRIT", show=False)
                continue
            debug_post_sent += 1

            eta_work_write += 1
            if progress and progress_key:
                progress.update_progress(progress_key, eta_work_write, eta_work_total)

        feed_ping_text = guild_data.get("text")
        if feed_ping_text and str(feed_ping_text).strip():
            await asyncio.sleep(2)
            try:
                await asyncio.wait_for(feed_data_hold.send(content=str(feed_ping_text).strip()), timeout=5.0)
                log(f"    ⤷ PING: SUCCESS", "feed", show=False)
            except Exception as e:
                log(f"    ⤷ [(!) FAILURE] #ERROR_FLAG_0003 | DUMP: {e} ", "feed", level="CRIT", show=False)
                continue

    # Igual que las noticias: al cerrar el ciclo quedan todos los hashes
    # actuales, aunque algún envío haya fallado. Si la lista supera el
    # tamaño del catálogo, se recortan los más viejos.
    write_notification(commit_hashes(notified, current_ordered, len(item_data), replace=False))

    log(f"[FEED - STORE]: [SENT: {debug_post_sent}]", "feed", show=False)
    log(f"[FEED - STORE]: THREAD CLOSED.", "feed", show=False)
    log(f" ", "feed", show=False)
    return debug_post_sent
