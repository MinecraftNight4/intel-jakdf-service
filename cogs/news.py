import json
import math
import os
from typing import Dict, Any

import discord
from discord import app_commands, ui
from discord.ext import commands

RAW_NEWS_FILE = "web_save/request_news.json"
ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF


class NewsPageView(ui.LayoutView):
    def __init__(self, article: dict, page: int, total_pages: int):
        super().__init__()

        uuid = article["article_uuid"]
        nodes = article.get("article_node", [])
        items = article.get("article_item", [])

        start = (page - 1) * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        page_nodes = nodes[start:end]
        page_items = items[start:end]

        # ===== Container principal =====
        rgb_hex = article.get("article_rgbs", "ffffff")
        try:
            accent = int(rgb_hex, 16)
        except (ValueError, TypeError):
            accent = ACCENT_COLOR
        container = ui.Container(accent_colour=accent)

        # Banner (logo)
        if article.get("article_logo"):
            gallery = ui.MediaGallery()
            gallery.add_item(media=article["article_logo"])
            container.add_item(gallery)

        # Título
        header = (
            f"# __{article['article_name']}__\n"
            f"[`🔗`](https://info.kj8-thegame.com/news/{uuid}"
            f"?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) "
            f"Posted on <t:{article['article_time']}>."
        )
        container.add_item(ui.TextDisplay(header))
        container.add_item(ui.Separator())
        
        # ===== Contenido agrupado =====
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
            container.add_item(ui.TextDisplay("*Sin contenido en esta página*"))

        container.add_item(ui.Separator())

        # ===== Botones DENTRO del Container =====
        row = ui.ActionRow()

        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="gamenews_menu"
        ))

        row.add_item(ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gamenews_{uuid}_{page-1}",
            disabled=page <= 1
        ))

        row.add_item(ui.Button(
            label=f"PAGE {page} OF {total_pages}",
            style=discord.ButtonStyle.success,
            custom_id=f"gamenews_{uuid}_info",
            disabled=True
        ))

        row.add_item(ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gamenews_{uuid}_{page+1}",
            disabled=page >= total_pages
        ))

        container.add_item(row)          # ← botones dentro del container
        self.add_item(container)


class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.raw_news: Dict[str, Any] = {}
        self.cache: Dict[str, NewsPageView] = {}   # ← aquí vive todo (solo memoria)
        self.load_raw()
        self.build_cache()

    def load_raw(self):
        try:
            if os.path.exists(RAW_NEWS_FILE):
                with open(RAW_NEWS_FILE, "r", encoding="utf-8") as f:
                    self.raw_news = json.load(f)
                print(f"✅ Datos crudos: {len(self.raw_news)} noticias")
            else:
                print(f"⚠️ No se encontró {RAW_NEWS_FILE}")
        except Exception as e:
            print(f"❌ Error cargando raw: {e}")

    def build_cache(self):
        """Destruye la caché anterior y la reconstruye."""
        self.cache.clear()

        for article in self.raw_news.values():
            total_items = len(article.get("article_node", []))
            total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1

            for page in range(1, total_pages + 1):
                key = f"gamenews_{article['article_uuid']}_{page}"
                self.cache[key] = NewsPageView(article, page, total_pages)

        print(f"✅ Caché reconstruida: {len(self.cache)} páginas en memoria")

    @app_commands.command(name="gamenews", description="Muestra una noticia (Components V2)")
    @app_commands.describe(article_id="ID del artículo", page="Página")
    async def gamenews(
        self,
        interaction: discord.Interaction,
        article_id: str = "1000030",
        page: app_commands.Range[int, 1, 50] = 1
    ):
        key = f"gamenews_{article_id}_{page}"
        await self._send(interaction, key)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("gamenews_"):
            return

        if custom_id == "gamenews_menu":
            await interaction.response.send_message("Menú de noticias", ephemeral=True)
            return

        await self._send(interaction, custom_id, edit=True)

    async def _send(self, interaction: discord.Interaction, key: str, edit: bool = False):
        view = self.cache.get(key)
        if view is None:
            await interaction.response.send_message(f"❌ `{key}` no está en la caché.", ephemeral=True)
            return

        try:
            if edit:
                await interaction.response.edit_message(view=view)
            else:
                await interaction.response.send_message(view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)

    @app_commands.command(name="rebuild_cache", description="Destruye y reconstruye la caché en memoria")
    @app_commands.default_permissions(administrator=True)
    async def rebuild_cache(self, interaction: discord.Interaction):
        self.load_raw()
        self.build_cache()
        await interaction.response.send_message(
            f"✅ Caché reconstruida. Páginas en memoria: `{len(self.cache)}`",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))