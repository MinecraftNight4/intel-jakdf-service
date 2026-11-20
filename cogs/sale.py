import json
import math
import os
import time
from typing import Any, Dict, List, Optional

import discord
from logger import log
from discord import app_commands, ui
from discord.ext import commands


# ============================================================
# /store
#
# Built once in Store.build_cache and swapped by custom_id.
# Rebuilt only when the sale catalog is reloaded.
#
#   store_menu
#   store_page_{section}_{page}
#   store_index_{section}_{page}
#   store_jump_{section}             page jumper; values are store_page_*
#   store_jump_pick_*                category dropdown; values are store_page_*_1
# ============================================================

SALE_FILE = "sys_save/request_sale.json"
STORE_URL = "https://webstore.kj8-thegame.com/?language=en"
FALLBACK_BANNER = "https://asset.kj8-thegame.com/static/production/images/en/webstore_kv-c686d07bdb76271fe016dbfe3a61063e.jpg"

ITEMS_PER_PAGE = 2
RECENT_ON_MENU = 4
PUBLIC_COOLDOWN = 60
MENU_COLOUR = 0xFF8C00
SECTION_COLOURS = (0xE67E22, 0x5C6BC0, 0x26A69A, 0xAB47BC, 0xEF5350)
ERROR_GIF = "https://media4.giphy.com/media/v1.Y2lkPTc5MGI3NjExZjI5cHBzeG16dHJyNDY4N2lxYmc1cDlnd2RjeTBmanBlZXViM2dkeSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/KDDljB0PQQaGjiG57X/giphy.gif"


def clip(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def safe_url(url: Any) -> Optional[str]:
    if not isinstance(url, str):
        return None
    url = url.strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def section_colour(index: int) -> int:
    if index < 1:
        return SECTION_COLOURS[0]
    return SECTION_COLOURS[(index - 1) % len(SECTION_COLOURS)]


def section_emoji(name: str) -> str:
    upper = (name or "").upper()
    if "CRYSTAL" in upper or "GEM" in upper:
        return "💎"
    if "PACK" in upper:
        return "📦"
    return "🛒"


def recent_line(entry: dict, listed_at: int) -> str:
    item = entry.get("item") or {}
    name = str(entry.get("name") or "Unknown").replace("\n", " ").strip()
    cost = item.get("cost")
    price = str(cost).strip() if cost is not None else ""
    if not price:
        price = "?"
    elif not price.upper().startswith("US$"):
        price = f"US${price}"
    if listed_at:
        return f"- `{price}` **{name}** · <t:{listed_at}:f>"
    return f"- `{price}` **{name}**"


def recent_offers(sections: List[dict], limit: int = RECENT_ON_MENU) -> List[tuple]:
    """Newest listings first. time_index is when the bot first saw the SKU."""
    found = []
    for section in sections:
        for entry in section.get("entries") or []:
            item = entry.get("item") or {}
            listed = item.get("time_index")
            listed_at = int(listed) if isinstance(listed, (int, float)) else 0
            found.append((listed_at, entry))
    found.sort(key=lambda row: row[0], reverse=True)
    return found[:limit]


def add_category_dropdown(
    container: ui.Container,
    sections: List[dict],
    custom_prefix: str,
    placeholder: str,
    current: Optional[int] = None,
) -> None:
    chunks = [sections[i:i + 25] for i in range(0, len(sections), 25)][:4]
    for chunk_index, chunk in enumerate(chunks, start=1):
        options = []
        for offset, section in enumerate(chunk):
            index = (chunk_index - 1) * 25 + offset + 1
            count = len(section.get("entries") or [])
            word = "offer" if count == 1 else "offers"
            options.append(discord.SelectOption(
                label=str(section.get("name") or f"Category {index}")[:100],
                description=f"{count} {word}"[:100],
                value=f"store_page_{index}_1",
                emoji=section_emoji(section.get("name") or ""),
                default=current == index,
            ))
        if not options:
            continue
        row = ui.ActionRow()
        row.add_item(ui.Select(
            custom_id=f"{custom_prefix}_{chunk_index}",
            placeholder=placeholder[:150],
            options=options,
            min_values=1,
            max_values=1,
        ))
        container.add_item(row)


def add_banner(container: ui.Container, banner: Optional[str]) -> None:
    media = safe_url(banner) or FALLBACK_BANNER
    gallery = ui.MediaGallery()
    gallery.add_item(media=media)
    container.add_item(gallery)


def add_rows(container: ui.Container, buttons: List[ui.Button]) -> None:
    for start in range(0, len(buttons), 5):
        row = ui.ActionRow()
        for button in buttons[start:start + 5]:
            row.add_item(button)
        container.add_item(row)


def catalog_note(raw: dict) -> str:
    lines: List[str] = []
    ping = raw.get("service-last_ping")
    if isinstance(ping, (int, float)):
        lines.append(f"-# ⏰ *The store is fetched every 30 minutes. Last fetch <t:{int(ping)}:R>.*")
    else:
        lines.append("-# ⏰ *The store is fetched every 30 minutes.*")

    fail = raw.get("service-last_fail")
    if isinstance(fail, str) and fail.strip():
        clean = " ".join(fail.split())[:180]
        lines.append(f"-# ⚠️ Last fetch failed. Showing the previous catalog. `{clean}`")
    return "\n".join(lines)


def page_count(total_items: int) -> int:
    if total_items <= 0:
        return 1
    return max(1, math.ceil(total_items / ITEMS_PER_PAGE))


class StorePageView(ui.LayoutView):
    def __init__(
        self,
        raw: dict,
        sections: List[dict],
        section_index: int,
        page: int,
    ):
        super().__init__(timeout=None)
        section = sections[section_index - 1]
        entries: List[dict] = section["entries"]
        total_pages = page_count(len(entries))
        page = min(max(1, page), total_pages)

        start = (page - 1) * ITEMS_PER_PAGE
        visible = entries[start:start + ITEMS_PER_PAGE]
        accent = section_colour(section_index)

        container = ui.Container(accent_colour=accent)
        add_banner(container, raw.get("service-last_logo"))

        offer_word = "offer" if len(entries) == 1 else "offers"
        container.add_item(ui.TextDisplay(clip(
            f"# {section_emoji(section['name'])} __{section['name']}__\n"
            f"-# Page {page} of {total_pages} · {len(entries)} {offer_word}"
        )))
        container.add_item(ui.Separator())

        if not visible:
            container.add_item(ui.TextDisplay("## __WELP... THIS SHELF IS EMPTY... `≡(▔﹏▔)≡`__"))
        else:
            for index, entry in enumerate(visible):
                if index:
                    container.add_item(ui.Separator())
                text = entry.get("text")
                if not isinstance(text, str) or not text.strip():
                    text = f"### {entry.get('name') or 'Unknown'}"
                icon = safe_url(entry.get("icon"))
                if icon:
                    container.add_item(ui.Section(
                        ui.TextDisplay(clip(text)),
                        accessory=ui.Thumbnail(
                            icon,
                            description=str(entry.get("name") or "Offer")[:256],
                        ),
                    ))
                else:
                    container.add_item(ui.TextDisplay(clip(text)))

        container.add_item(ui.Separator())
        if len(sections) > 1:
            add_category_dropdown(
                container,
                sections,
                custom_prefix=f"store_jump_shelf{section_index}",
                placeholder="Change category",
                current=section_index,
            )

        pager = [
            ui.Button(
                label="≡ MENU",
                style=discord.ButtonStyle.danger,
                custom_id="store_menu",
            ),
            ui.Button(
                emoji="◀️",
                style=discord.ButtonStyle.secondary,
                custom_id=f"store_page_{section_index}_{page - 1}",
                disabled=page <= 1,
            ),
            ui.Button(
                label=f"PAGE {page} OF {total_pages}",
                style=discord.ButtonStyle.success,
                custom_id=f"store_index_{section_index}_{page}",
                disabled=total_pages <= 1,
            ),
            ui.Button(
                emoji="▶️",
                style=discord.ButtonStyle.secondary,
                custom_id=f"store_page_{section_index}_{page + 1}",
                disabled=page >= total_pages,
            ),
            ui.Button(
                label="Web Store",
                emoji="🌐",
                style=discord.ButtonStyle.link,
                url=STORE_URL,
            ),
        ]
        add_rows(container, pager)
        self.add_item(container)


class StoreIndexView(ui.LayoutView):
    def __init__(self, section: dict, section_index: int, current_page: int):
        super().__init__(timeout=None)
        entries: List[dict] = section["entries"]
        total_pages = page_count(len(entries))
        current_page = min(max(1, current_page), total_pages)

        container = ui.Container(accent_colour=section_colour(section_index))
        container.add_item(ui.TextDisplay(
            f"## {section_emoji(section['name'])} __{section['name']}__\n"
            f"-# Jump to a page. You are on page {current_page} of {total_pages}."
        ))

        if total_pages <= 25:
            pages = list(range(1, total_pages + 1))
            need_first = need_last = False
        else:
            start = max(1, current_page - 11)
            end = min(total_pages, (start + 22) - 1)
            start = max(1, (end - 22) + 1)
            pages = list(range(start, end + 1))
            need_first = start > 1
            need_last = end < total_pages

        options: List[discord.SelectOption] = []
        if need_first:
            options.append(discord.SelectOption(
                label="JUMP TO PAGE 1",
                value=f"store_page_{section_index}_1",
                emoji="🏚️",
            ))

        for number in pages:
            options.append(discord.SelectOption(
                label=f"PAGE {number} OF {total_pages}",
                value=f"store_page_{section_index}_{number}",
                emoji="📍" if number == current_page else "⏩",
            ))

        if need_last:
            options.append(discord.SelectOption(
                label=f"JUMP TO PAGE {total_pages}",
                value=f"store_page_{section_index}_{total_pages}",
                emoji="🚪",
            ))

        # First/last jumps can duplicate a page already in the window.
        unique: List[discord.SelectOption] = []
        seen = set()
        for option in options:
            if option.value in seen:
                continue
            seen.add(option.value)
            unique.append(option)
        options = unique[:25]

        select = ui.Select(
            custom_id=f"store_jump_{section_index}",
            placeholder=f"Jump to page… (now {current_page}/{total_pages})",
            options=options,
            min_values=1,
            max_values=1,
        )
        row = ui.ActionRow()
        row.add_item(select)
        container.add_item(row)

        back = ui.ActionRow()
        back.add_item(ui.Button(
            label="← BACK",
            style=discord.ButtonStyle.secondary,
            custom_id=f"store_page_{section_index}_{current_page}",
        ))
        container.add_item(back)
        self.add_item(container)


class StoreMenuView(ui.LayoutView):
    def __init__(self, raw: dict, sections: List[dict]):
        super().__init__(timeout=None)
        container = ui.Container(accent_colour=MENU_COLOUR)
        add_banner(container, raw.get("service-last_logo"))

        total = sum(len(section["entries"]) for section in sections)
        offer_word = "offer" if total == 1 else "offers"
        category_word = "category" if len(sections) == 1 else "categories"
        container.add_item(ui.TextDisplay(clip(
            f"## [`🔗`]({STORE_URL}) KAIJU NO.8 - THE GAME | WEB STORE\n"
            f"-# {total} {offer_word} · {len(sections)} {category_word}\n"
            f"{catalog_note(raw)}"
        )))
        container.add_item(ui.Separator())

        if not sections or total == 0:
            fail = raw.get("service-last_fail")
            reason = fail.strip() if isinstance(fail, str) and fail.strip() else "The web store did not return a catalog."
            container.add_item(ui.TextDisplay(clip(
                "## __WELP... THIS IS EMPTY... `≡(▔﹏▔)≡`__\n"
                f"{reason}\n"
                "-# `error_store_empty`"
            )))
        else:
            latest = recent_offers(sections)
            lines = [recent_line(entry, listed_at) for listed_at, entry in latest]
            hidden = total - len(latest)
            more = f"\n-# +{hidden} more. Pick a category below." if hidden > 0 else ""
            container.add_item(ui.TextDisplay(clip(
                "### Latest detected\n"
                + "\n".join(lines)
                + more
            )))
            add_category_dropdown(
                container,
                sections,
                custom_prefix="store_jump_pick",
                placeholder="Choose a category",
            )

        self.add_item(container)


class StoreErrorView(ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        container = ui.Container()

        gallery = ui.MediaGallery()
        gallery.add_item(media=ERROR_GIF)
        container.add_item(gallery)

        container.add_item(ui.TextDisplay(
            "## WHY IS NO.8 HERE!? (＃°Д°)\n"
            "Somehow you have requested to view a panel, menu or page that no longer exist or is empty.\n"
            "-# `error_store_notavailable`"
        ))

        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="store_menu",
        ))
        container.add_item(row)
        self.add_item(container)


class Store(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.raw: Dict[str, Any] = {}
        self.sections: List[dict] = []
        self.cache: Dict[str, ui.LayoutView] = {}
        self.menu_view: Optional[StoreMenuView] = None
        self.error_view: Optional[StoreErrorView] = None
        self._public_cooldowns: Dict[int, float] = {}
        self.load_raw()
        self.build_cache()

    def load_raw(self):
        try:
            if os.path.exists(SALE_FILE):
                with open(SALE_FILE, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self.raw = data if isinstance(data, dict) else {}
                count = len(self.raw.get("item_data") or {})
                log(f"DATABASE: Store offers x{count}", "store", show=False)
            else:
                log("DATABASE: Store offers x0 [THE FILE DOESN'T EXIST]!", "store", "CRIT", show=False)
                self.raw = {}
        except Exception as exc:
            log(f"DATABASE EXCEPTION! {exc}", "store", "CRIT", show=False)
            self.raw = {}

    def _collect_sections(self) -> List[dict]:
        pack = self.raw.get("pack_data") or {}
        views = self.raw.get("view_data") or {}
        items = self.raw.get("item_data") or {}
        if not isinstance(pack, dict):
            return []
        if not isinstance(views, dict):
            views = {}
        if not isinstance(items, dict):
            items = {}

        sections: List[dict] = []
        for key, section in pack.items():
            if not isinstance(section, dict):
                continue
            name = str(section.get("name") or key).strip() or str(key)
            sku_list = section.get("list") or []
            if not isinstance(sku_list, list):
                sku_list = []
            cards = views.get(key) or []
            if not isinstance(cards, list):
                cards = []

            entries = []
            for index, sku in enumerate(sku_list):
                card = cards[index] if index < len(cards) and isinstance(cards[index], dict) else {}
                item = items.get(sku)
                if not isinstance(item, dict):
                    item = {}
                text = card.get("text") if isinstance(card.get("text"), str) else None
                if not text:
                    text = item.get("text_entry") if isinstance(item.get("text_entry"), str) else None
                icon = card.get("icon") if card.get("icon") else item.get("icon")
                entries.append({
                    "sku": str(sku),
                    "text": text or "",
                    "icon": icon,
                    "name": item.get("name") or str(sku),
                    "item": item,
                })
            sections.append({"id": str(key), "name": name, "entries": entries})
        return sections

    def build_cache(self):
        sections = self._collect_sections()
        cache: Dict[str, ui.LayoutView] = {}
        page_total = 0
        index_total = 0
        for index, section in enumerate(sections, start=1):
            total = page_count(len(section["entries"]))
            for page in range(1, total + 1):
                cache[f"store_page_{index}_{page}"] = StorePageView(
                    self.raw, sections, index, page
                )
                page_total += 1
                if total > 1:
                    cache[f"store_index_{index}_{page}"] = StoreIndexView(section, index, page)
                    index_total += 1

        self.sections = sections
        self.cache = cache
        self.menu_view = StoreMenuView(self.raw, sections)
        self.error_view = StoreErrorView()
        log(
            f"ITEMS CACHED AT [cogs/store.py]: SECTIONS x{len(sections)}, "
            f"PAGES x{page_total}, JUMPS x{index_total}",
            "cache",
            show=False,
        )

    @app_commands.command(name="store", description="Browse the web store of «Kaiju No.8 The Game».")
    @app_commands.describe(private="This makes the command visible or hidden for everyone else.")
    async def store(self, interaction: discord.Interaction, private: bool = True):
        if not private:
            now = time.time()
            channel_id = interaction.channel_id or 0
            expires = self._public_cooldowns.get(channel_id, 0)
            if now < expires:
                remaining = int(expires - now)
                await interaction.response.send_message(
                    f"⏳ Not so fast! To prevent spam, the command is locked for **{remaining}s**.",
                    ephemeral=True,
                )
                return
            self._public_cooldowns[channel_id] = now + PUBLIC_COOLDOWN

        view = self.menu_view or self.error_view
        if view is None:
            await interaction.response.send_message(
                "❌ Currently this feature is not available! `error_store_empty`",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(view=view, ephemeral=private)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        data = interaction.data or {}
        custom_id = data.get("custom_id") or ""
        if not isinstance(custom_id, str) or not custom_id.startswith("store_"):
            return

        if custom_id == "store_menu":
            await self._respond(interaction, self.menu_view or self.error_view or StoreErrorView())
            return

        if custom_id.startswith("store_shelf_"):
            parts = custom_id.split("_")
            key = ""
            if len(parts) == 3:
                key = f"store_page_{parts[2]}_1"
            view = self.cache.get(key) or self.error_view or StoreErrorView()
            await self._respond(interaction, view)
            return

        if custom_id.startswith("store_jump_"):
            values = data.get("values") or []
            key = values[0] if values else ""
            view = self.cache.get(key) or self.error_view or StoreErrorView()
            await self._respond(interaction, view)
            return

        if custom_id.startswith("store_index_") or custom_id.startswith("store_page_"):
            view = self.cache.get(custom_id) or self.error_view or StoreErrorView()
            await self._respond(interaction, view)
            return

        await self._respond(interaction, self.error_view or StoreErrorView())

    async def _respond(self, interaction: discord.Interaction, view: ui.LayoutView):
        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.edit_message(view=view)
        except discord.errors.InteractionResponded:
            try:
                await interaction.followup.send(view=view, ephemeral=True)
            except Exception:
                pass
        except Exception as exc:
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(view=view, ephemeral=True)
                else:
                    await interaction.followup.send(view=view, ephemeral=True)
            except Exception:
                log(f"[STORE] _respond failed completely: {exc}", "store", level="CRIT", show=False)


async def setup(bot: commands.Bot):
    log("[COMMAND BUILDER]: /STORE", "slash", show=False)
    await bot.add_cog(Store(bot))
    log("[COMMAND BUILDER]: /STORE (Thread closed!)", "slash", show=False)
    log(" ", "slash", show=False)
