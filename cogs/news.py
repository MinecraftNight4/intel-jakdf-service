import json
import math
import os
import time
from typing import Dict, Any, List

import discord
from logger import info, warn, crit, log
from discord import app_commands, ui
from discord.ext import commands

RAW_NEWS_FILE = "sys_save/request_news.json"
ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFFFFFF
MAX_NEWS_IN_MENU = 100
OPTIONS_PER_DROPDOWN = 25
MAX_DROPDOWNS = 4
PUBLIC_COOLDOWN = 60


#   ===================================================
#   DEFINE EL HORARIO DEL POSTEO
#   ===================================================
def display_time_posted(unix_ts: int) -> str:
    diff = max(0, int(time.time()) - int(unix_ts))
    units = [
        (31536000, "year"),
        (2592000, "month"),
        (604800, "week"),
        (86400, "day"),
        (3600, "hour"),
        (60, "minute"),
    ]
    for seconds, name in units:
        value = diff // seconds
        if value >= 1:
            return f"1 {name} ago" if value == 1 else f"{value} {name}s ago"
    return "just now"

#   ===================================================
#   INDEXA EL EMOJI SEGUN EL TIPO DE NOTICIA
#   ===================================================
def display_emoji_types(article_type: str) -> str:
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



#   ===================================================
#   REGISTRO DE NOTICIAS POR PAGINA
#   ===================================================
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
            container.add_item(ui.TextDisplay("*`error_missing_text`*"))

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
            custom_id=f"gamenews_{uuid}_index_{page}",
            disabled=total_pages <= 1
        ))
        row.add_item(ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gamenews_{uuid}_{page+1}",
            disabled=page >= total_pages
        ))
        container.add_item(row)
        self.add_item(container)


class NewsPageIndexView(ui.LayoutView):
    def __init__(self, article: dict, current_page: int, total_pages: int):
        super().__init__()
        container = ui.Container(accent_colour=0xFF8C00)
        
        uuid = article["article_uuid"]
        nodes = article.get("article_node", [])
        items = article.get("article_item", [])
        title = article.get("article_name", "Unknown")
        container.add_item(ui.TextDisplay(f"## __{title}__"))
        
        if total_pages <= 25:
            #   SI HAY 25 ELEMENTOS O MENOS, no se muestra el SALTAR a Inicio/Fin.
            pages = list(range(1, total_pages + 1))
            need_first = need_last = False
        else:
            #   SUPERANDO LOS 25 ELEMENTOS, calcula cuantos elementos listar por arriba y abajo del index.
            start = max(1, (current_page - 11) ) 
            end = min(total_pages, ((start + 22) - 1) )
            start = max(1, ((end - 22) + 1) )

            pages = list(range(start, end + 1))
            need_first = start > 1
            need_last = end < total_pages

        options: list[discord.SelectOption] = []
        if need_first:   # JUMP FIRST PAGE
            options.append(discord.SelectOption(
                label="JUMP TO PAGE 1",
                value=f"gamenews_{uuid}_1",
                emoji="🏚️"
            ))
        for p in pages:   # LISTED PAGES
            is_current = p == current_page
            start = (p - 1) * ITEMS_PER_PAGE
            end = start + ITEMS_PER_PAGE
            
            page_raws = article.get("article_raws", [])[start:end]
            description = next(
                (str(r).strip()[:100] for r in page_raws if r and str(r).strip()),
                None
            )
            
            options.append(discord.SelectOption(
                label=f"PAGE {p} OF {total_pages}",
                value=f"gamenews_{uuid}_{p}",
                emoji="📍" if is_current else "⏩",
                description=description or None,
            ))
        if need_last:   # JUMP FINAL PAGE
            options.append(discord.SelectOption(
                label=f"JUMP TO PAGE {total_pages}",
                value=f"gamenews_{uuid}_{total_pages}",
                emoji="🚪"
            ))
        options = options[:25]
        select = ui.Select(
            custom_id=f"gamenews_{uuid}_redirect_1",
            placeholder=f"Jump to page… (now {current_page}/{total_pages})",
            options=options,
            min_values=1,
            max_values=1
        )
        row = ui.ActionRow()
        row.add_item(select)
        container.add_item(row)

        row_back = ui.ActionRow()
        row_back.add_item(ui.Button(
            label="← LEAVE",
            style=discord.ButtonStyle.secondary,
            custom_id=f"gamenews_{uuid}_{current_page}"
        ))
        container.add_item(row_back)
        
        self.add_item(container)


class NewsMenuView(ui.LayoutView):
    def __init__(self, sorted_articles: List[dict]):
        super().__init__()
        
        # COLOR
        container = ui.Container(accent_colour=0xFF8C00)

        # TITLE
        refresh_ts = int(time.time()) + 1800
        container.add_item(ui.TextDisplay(f"## [`🔗`](https://info.kj8-thegame.com/news?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) KAIJU NO.8 - THE GAME | IN-GAME NEWS \n-# ⏰ *News are fetched every 30 minutes. Fetching <t:{refresh_ts}:R>...*"))
        
        # BANNER
        gallery = ui.MediaGallery()
        gallery.add_item(media="https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/3393070/68c7e753b54b52465e99d8fffd4b4084a15db103/header.jpg")
        container.add_item(gallery)

        # SEPARATOR
        container.add_item(ui.Separator())

        # DROPDOWNS
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
                art_type = art.get("article_type", "news").upper()
                days_text = display_time_posted(art.get("article_time", 0))
                desc = f"{art_type} | {days_text}"[:100]
                uuid = art["article_uuid"]

                options.append(discord.SelectOption(
                    label=name,
                    description=desc,
                    value=f"gamenews_{uuid}_1",
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
            container.add_item(ui.TextDisplay("Kaijus are jamming our connection!! \n-# `error_articlewheel_empty`"))
        self.add_item(container)

class NewsErrorView(ui.LayoutView):
    def __init__(self):
        super().__init__()
        container = ui.Container()

        # MEME GIF
        gallery = ui.MediaGallery()
        gallery.add_item(media="https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExZjI5cHBzeG16dHJyNDY4N2lxYmc1cDlnd2RjeTBmanBlZXViM2dkeSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/KDDljB0PQQaGjiG57X/giphy.gif")
        container.add_item(gallery)

        # ERROR MESSAGE
        container.add_item(ui.TextDisplay("## WHY IS NO.8 HERE!? (＃°Д°)\nSomehow you have requested to view a panel, menu or article that no longer exist or is empty.\n-# `error_gamenews_notavailable`"))

        # BUTTON FALLBACK TO THE MENU
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
        self._public_cooldowns: Dict[int, float] = {}

        self.load_raw()
        self.build_cache()

    def load_raw(self):
        try:
            if os.path.exists(RAW_NEWS_FILE):
                with open(RAW_NEWS_FILE, "r", encoding="utf-8") as f:
                    self.raw_news = json.load(f)
                log(f"DATABASE: Articles stored x{len(self.raw_news)}", "news", show=False)
            else:
                log(f"DATABASE: Articles stored x0 [THE FILE DOESN'T EXIST]!", "cache", "CRIT", show=False)
                self.raw_news = {}
        except Exception as e:
            log(f"DATABASE EXCEPTION! {e}", "news", "CRIT", show=False)
            self.raw_news = {}

    def build_cache(self):
        self.cache.clear()
        self.sorted_articles = []

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
        log(f"ITEMS CACHED AT [cogs/news.py]: NEWS x{len(self.sorted_articles)}, PAGES x{len(self.cache)}", "cache", show=False)

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
            expires = self._public_cooldowns.get(interaction.channel_id, 0)
            if now < expires:
                remaining = int(expires - now)
                await interaction.response.send_message(
                    f"⏳ Not so fast! To prevent spam, the command is locked for **{remaining}s**.",
                    ephemeral=True
                )
                return
            self._public_cooldowns[interaction.channel_id] = now + PUBLIC_COOLDOWN
        
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
        is_private_request = custom_id.startswith("private_gamenews_")
        if is_private_request:
            custom_id = custom_id.replace("private_gamenews_", "gamenews_", 1)

        if not custom_id.startswith("gamenews_"):
            return

        # ---------- MENU ----------
        if custom_id == "gamenews_menu":
            view = self.menu_view or self.error_view or NewsErrorView()
            await self._respond(interaction, view, force_private=is_private_request)
            return
        
        # ---------- Dropdown del menú principal ----------
        if custom_id.startswith("gamenews_index_"):
            values = interaction.data.get("values", [])
            if not values:
                await self._respond(interaction, self.error_view or NewsErrorView(), force_private=is_private_request)
                return

            key = values[0]
            view = self.cache.get(key) or self.error_view or NewsErrorView()
            await self._respond(interaction, view, force_private=is_private_request)
            return
        
        # ---------- Botón "PAGE X OF Y" → índice ----------
        if "_index_" in custom_id and not custom_id.startswith("gamenews_index_"):
            parts = custom_id.split("_")
            if len(parts) >= 4 and parts[-2] == "index":
                try:
                    page = int(parts[-1])
                    uuid = "_".join(parts[1:-2])
                except ValueError:
                    await interaction.response.edit_message(view=self.error_view or NewsErrorView())
                    return

                article = None
                for art in self.sorted_articles:
                    if art.get("article_uuid") == uuid:
                        article = art
                        break
            
                if article is None:
                    await interaction.response.edit_message(view=self.error_view or NewsErrorView())
                    return
            
                total_items = len(article.get("article_node", []))
                total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1
            
            view = NewsPageIndexView(article, page, total_pages)
            await self._respond(interaction, view, force_private=is_private_request)
            return
        
        # ---------- Dropdown de páginas (redirect) ----------
        if "_redirect_" in custom_id:
            values = interaction.data.get("values", [])
            if not values:
                await self._respond(interaction, self.error_view or NewsErrorView(), force_private=is_private_request)
                return
    
            key = values[0]
            view = self.cache.get(key) or self.error_view or NewsErrorView()
            await self._respond(interaction, view, force_private=is_private_request)
            return
        
        view = self.cache.get(custom_id) or self.error_view or NewsErrorView()
        await self._respond(interaction, view, force_private=is_private_request)

    async def _respond(self, interaction, view, *, force_private: bool = False):
        if force_private:
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(view=view)
    
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


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))