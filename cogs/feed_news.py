import json
import math
import os
import time
from typing import Dict, Any, List

import discord
from discord import app_commands, ui
from discord.ext import commands

FEED_ITEMS_PER_PAGE = 4   # ← configurable

class FeedNewsPageView(ui.LayoutView):
    def __init__(self, article: dict, items_per_page: int = FEED_ITEMS_PER_PAGE):
        super().__init__()

        uuid = article["article_uuid"]
        nodes = article.get("article_node", [])
        items = article.get("article_item", [])
        total_items = len(nodes)
        total_pages = max(1, math.ceil(total_items / items_per_page)) if total_items else 1

        # Solo página 1
        page_nodes = nodes[:items_per_page]
        page_items = items[:items_per_page]

        rgb_hex = article.get("article_rgbs", "ffffff")
        try:
            accent = int(rgb_hex, 16)
        except (ValueError, TypeError):
            accent = 0xFFFFFF

        container = ui.Container(accent_colour=accent)

        if article.get("article_logo"):
            gallery = ui.MediaGallery()
            gallery.add_item(media=article["article_logo"])
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

        if len(container.children) <= (2 if article.get("article_logo") else 1):
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