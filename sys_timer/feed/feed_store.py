import io
import hashlib
import discord

from typing import Dict, Any, List, Optional
from discord.ext import commands
from discord import ui

import feed_store
from logger import log

from .__feed import (
    Image,
    Message,
    commit_history,
    deliver,
    fetch_image,
    load_history,
    load_json,
)

# -------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------
ACCENT_FALLBACK = 0x5865F2
STORE_URL = "https://webstore.kj8-thegame.com/?language=en"

SALE_FILE = "sys_save/request_sale.json"

NAMESPACE = "feed_game_store"
TAG = "STORE"


def color_from_sku(sku: str) -> int:
    """Stable accent colour derived from the item SKU."""
    digest = hashlib.sha256(sku.encode("utf-8")).digest()
    red = 48 + digest[0] % 208
    green = 48 + digest[1] % 208
    blue = 48 + digest[2] % 208
    return (red << 16) | (green << 8) | blue


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


def _make_store_message(sku: str, item: dict, item_hash: str, banner: Optional[Image]) -> Message:
    def make() -> dict:
        files = None
        icon = None
        if banner is not None:
            # un discord.File no se puede reutilizar: se crea uno nuevo por envío
            files = [discord.File(io.BytesIO(banner.data), filename=banner.name)]
            icon = f"attachment://{banner.name}"
        return {"view": FeedStoreItemView(sku, item, banner=icon), "files": files}

    return Message(uid=item_hash, label=str(item.get("name") or sku), make=make)


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

    banner_url = sale.get("service-last_logo")
    if not isinstance(banner_url, str):
        banner_url = None

    targets = feed_store.targets(NAMESPACE)
    previous = load_history(NAMESPACE)
    already_sent = set(previous)

    #=================#
    # PROCESS OF DATA #
    #=================#
    current: List[str] = []
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
            current.append(item_hash)
            if item_hash not in already_sent:
                process_post.append((str(sku), item, item_hash))

    log(f"[FEED - {TAG}]: [CHANNELS: {len(targets)}] [ARTICLES: {len(process_post)}/{len(item_data)}]", "feed", show=False)

    #==============#
    # CLOSE THREAD #
    #==============#
    if not targets or not process_post:
        commit_history(NAMESPACE, previous, current, keep=len(item_data), replace=True)
        log(f"[FEED - {TAG}]: THREAD CLOSED.", "feed", show=False)
        log("", "feed", show=False)
        return 0

    #==================#
    # MESSAGE DELIVERY #
    #==================#
    banner = await fetch_image(banner_url, prefix="store_logo")
    messages = [_make_store_message(sku, item, h, banner) for sku, item, h in process_post]

    sent = await deliver(bot, TAG, targets, messages, progress=progress, progress_key=progress_key)

    # Igual que las noticias: al cerrar el ciclo quedan todos los hashes
    # actuales, aunque algún envío haya fallado. Si la lista supera el
    # tamaño del catálogo, se recortan los más viejos.
    commit_history(NAMESPACE, previous, current, keep=len(item_data), replace=False)

    log(f"[FEED - {TAG}]: [SENT: {sent}]", "feed", show=False)
    log(f"[FEED - {TAG}]: THREAD CLOSED.", "feed", show=False)
    log(" ", "feed", show=False)
    return sent
