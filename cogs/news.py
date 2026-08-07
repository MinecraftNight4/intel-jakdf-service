import json
import math
import os
import time
from typing import Dict, Any, List

import discord
from discord import app_commands, ui
from discord.ext import commands

RAW_NEWS_FILE = "web_save/request_news.json"
ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF
MAX_NEWS_IN_MENU = 100
OPTIONS_PER_DROPDOWN = 25
MAX_DROPDOWNS = 4
PUBLIC_COOLDOWN = 60  # segundos


def display_time_posted(unix_ts: int) -> str:
    """Convierte article_time (unix) en texto legible de días."""
    now = int(time.time())
    diff = max(0, now - int(unix_ts))
    days = diff // 86400

    if days == 0:
        return "Today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"

def display_emoji_types(article_type: str) -> str:
    """Devuelve el emoji según el tipo de noticia."""
    t = (article_type or "").strip().lower()
    mapping = {
        "maintenance": "🚧",
        "important": "⚠️",
        "update": "📥",
        "event": "🎉",
        "gacha": "🎫",
        "news": "📰",
        "known issue": "🔥",
    }
    return mapping.get(t, "⁉️")


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

        rgb_hex = article.get("article_rgbs", "ffffff")
        try:
            accent = int(rgb_hex, 16)
        except (ValueError, TypeError):
            accent = ACCENT_COLOR

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
            container.add_item(ui.TextDisplay("*Sin contenido en esta página*"))

        container.add_item(ui.Separator())

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
        container.add_item(row)
        self.add_item(container)


class NewsMenuView(ui.LayoutView):
    def __init__(self, sorted_articles: List[dict]):
        super().__init__()
        refresh_ts = int(time.time()) + 1800

        container = ui.Container(accent_colour=0xFF8C00)

        header_text = (
            f"## [`🔗`](https://info.kj8-thegame.com/news?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) "
            f"KAIJU NO.8 - THE GAME | IN-GAME NEWS\n"
            f"-# ⏰ *This menu will be updated in <t:{refresh_ts}:R>*"
        )
        container.add_item(ui.TextDisplay(header_text))
        gallery = ui.MediaGallery()
        gallery.add_item(
            media="https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/3393070/68c7e753b54b52465e99d8fffd4b4084a15db103/header.jpg"
        )
        container.add_item(gallery)

        # 3) Separator
        container.add_item(ui.Separator())

        # 4) Dropdowns (máximo 4 × 25 = 100)
        articles = sorted_articles[:MAX_NEWS_IN_MENU]
        total = len(articles)
        num_dropdowns = min(MAX_DROPDOWNS, math.ceil(total / OPTIONS_PER_DROPDOWN) if total else 0)

        for i in range(num_dropdowns):
            start = i * OPTIONS_PER_DROPDOWN
            end = start + OPTIONS_PER_DROPDOWN
            chunk = articles[start:end]

            options = []
            for art in chunk:
                name = art.get("article_name", "Unknown")[:100]
                art_type = art.get("article_type", "news")
                days_text = display_time_posted(art.get("article_time", 0))
                desc = f"{art_type} | {days_text}"[:100]

                options.append(discord.SelectOption(
                    label=name,
                    description=desc,
                    value=str(art["article_uuid"]),
                    emoji=display_emoji_types(art_type)
                ))

            select = ui.Select(
                custom_id=f"gamenews_index_{i + 1}",
                placeholder=f"Tap to read an article | N°{i + 1}",
                options=options,
                min_values=1,
                max_values=1
            )
            row = ui.ActionRow()
            row.add_item(select)
            container.add_item(row)

        if num_dropdowns == 0:
            container.add_item(ui.TextDisplay("*No hay noticias disponibles.*"))

        self.add_item(container)

class NewsErrorView(ui.LayoutView):
    def __init__(self):
        super().__init__()

        container = ui.Container(accent_colour=0xFF0000)

        gallery = ui.MediaGallery()
        gallery.add_item(
            media="https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExZjI5cHBzeG16dHJyNDY4N2lxYmc1cDlnd2RjeTBmanBlZXViM2dkeSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/KDDljB0PQQaGjiG57X/giphy.gif"
        )
        container.add_item(gallery)

        container.add_item(ui.TextDisplay(
            "## WHY IS NO.8 HERE!?\nThis article or menu is not longer available..."
        ))

        container.add_item(ui.Separator())

        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="gamenews_menu"
        ))
        container.add_item(row)

        self.add_item(container)

class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.raw_news: Dict[str, Any] = {}
        self.cache: Dict[str, NewsPageView] = {}
        self.sorted_articles: List[dict] = []
        self.menu_view: NewsMenuView | None = None
        self.error_view: NewsErrorView | None = None
        self._public_cooldowns: Dict[int, float] = {}  # user_id -> timestamp fin cooldown

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
                self.raw_news = {}
        except Exception as e:
            print(f"❌ Error cargando raw: {e}")
            self.raw_news = {}

    def build_cache(self):
        self.cache.clear()
        self.sorted_articles = []

        # Ordenar por article_time descendente (más recientes primero)
        articles = list(self.raw_news.values())
        articles.sort(key=lambda a: int(a.get("article_time", 0)), reverse=True)
        self.sorted_articles = articles

        for article in articles:
            total_items = len(article.get("article_node", []))
            total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1

            for page in range(1, total_pages + 1):
                key = f"gamenews_{article['article_uuid']}_{page}"
                self.cache[key] = NewsPageView(article, page, total_pages)

        # Menú siempre fresco
        self.menu_view = NewsMenuView(self.sorted_articles)
        self.error_view = NewsErrorView()
        print(f"✅ Caché reconstruida: {len(self.cache)} páginas | {len(self.sorted_articles)} noticias")

    # ------------------------------------------------------------------
    # /news [private]
    # ------------------------------------------------------------------
    @app_commands.command(name="news", description="Read the in-game news of «Kaiju No.8 The Game».")
    @app_commands.describe(private="This makes the command visible or hidden for everyone else.")
    async def news(
        self,
        interaction: discord.Interaction,
        private: bool = True
    ):
        if not private:
            now = time.time()
            expires = self._public_cooldowns.get(interaction.user.id, 0)
            if now < expires:
                remaining = int(expires - now)
                await interaction.response.send_message(
                    f"⏳ Not so fast! To prevent spam, the command is locked for **{remaining}s**.",
                    ephemeral=True
                )
                return
            self._public_cooldowns[interaction.user.id] = now + PUBLIC_COOLDOWN
        
        if self.menu_view is None:
            await interaction.response.send_message("❌ Currently this feature is not available! `error_menuindex_empty`", ephemeral=True)
            return
        
        await interaction.response.send_message(
            view=self.menu_view,
            ephemeral=private
        )

    # ------------------------------------------------------------------
    # Listener de componentes
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("gamenews_"):
            return

        # Botón MENU → volver al menú
        if custom_id == "gamenews_menu":
            if self.menu_view is None:
                await interaction.response.send_message(
                    view=self.error_view or NewsErrorView(),
                    ephemeral=True
                )
                return
            await interaction.response.edit_message(view=self.menu_view)
            return

        # Dropdown de índice → abrir primera página de la noticia
        if custom_id.startswith("gamenews_index_"):
            values = interaction.data.get("values", [])
            if not values:
                await interaction.response.edit_message(
                    view=self.error_view or NewsErrorView()
                )
                return

            article_uuid = values[0]
            key = f"gamenews_{article_uuid}_1"
            view = self.cache.get(key)
            if view is None:
                await interaction.response.edit_message(
                    view=self.error_view or NewsErrorView()
                )
                return

            await interaction.response.edit_message(view=view)
            return

        # Navegación de páginas (botones ◀️ ▶️)
        await self._send(interaction, custom_id, edit=True)

    async def _send(self, interaction: discord.Interaction, key: str, edit: bool = False):
        view = self.cache.get(key)
        if view is None:
            err = self.error_view or NewsErrorView()
            try:
                if edit:
                    await interaction.response.edit_message(view=err)
                else:
                    await interaction.response.send_message(view=err, ephemeral=True)
            except Exception:
                await interaction.response.send_message(view=err, ephemeral=True)
            return
    
        try:
            if edit:
                await interaction.response.edit_message(view=view)
            else:
                await interaction.response.send_message(view=view)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: `{e}`", ephemeral=True)

    # ------------------------------------------------------------------
    # /rebuild_cache
    # ------------------------------------------------------------------
    @app_commands.command(name="rebuild_cache", description="Destruye y reconstruye la caché en memoria")
    @app_commands.default_permissions(administrator=True)
    async def rebuild_cache(self, interaction: discord.Interaction):
        self.load_raw()
        self.build_cache()
        await interaction.response.send_message(
            f"✅ Caché reconstruida.\n"
            f"• Páginas: `{len(self.cache)}`\n"
            f"• Noticias: `{len(self.sorted_articles)}`",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))