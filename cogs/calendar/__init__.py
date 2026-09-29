
# cogs/calendar/__init__.py
import os
import time
from typing import Dict, Optional

import discord
from discord import File, app_commands, ui
from discord.ext import commands
from logger import log

from .helpers import PUBLIC_COOLDOWN, status_show_display
from .item_coming import panelbuilder_coming
from .item_events import panelbuilder_events
from .item_gachas import (
    collect_active_banners,
    create_gacha_banner_image,
    get_gacha_attachment,
    panelbuilder_gachas,
)
from .item_resets import panelbuilder_resets
from .item_status import panelbuilder_status


class Calendar(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: Dict[str, ui.LayoutView] = {}
        self.default_key = "gachas_a"
        self._public_cooldowns: Dict[int, float] = {}
        self.rebuild_calendar_cache()

    def rebuild_calendar_cache(self):
        log("[CALENDAR]: Rebuilding cache...", "calendar", show=False)

        # Imagen UNA vez al reconstruir el calendario
        try:
            banners = collect_active_banners()
            if banners:
                create_gacha_banner_image(banners)
                log("[CALENDAR]: Gacha image generated", "calendar", show=False)
        except Exception as e:
            log(f"[CALENDAR] Failed to generate gacha image: {e}", "calendar", level="CRIT", show=False)

        self.cache["status_b"] = panelbuilder_status(relative=False)
        self.cache["status_a"] = panelbuilder_status(relative=True)

        self.cache["gachas_b"] = panelbuilder_gachas(relative=False)
        self.cache["gachas_a"] = panelbuilder_gachas(relative=True)

        self.cache["events_b"] = panelbuilder_events(relative=False)
        self.cache["events_a"] = panelbuilder_events(relative=True)

        self.cache["coming_b"] = panelbuilder_coming(relative=False)
        self.cache["coming_a"] = panelbuilder_coming(relative=True)

        self.cache["resets_b"] = panelbuilder_resets(relative=False)
        self.cache["resets_a"] = panelbuilder_resets(relative=True)

        self.default_key = "status_a" if status_show_display() else "gachas_a"
        log(f"[CALENDAR]: Cache rebuilt → default: {self.default_key}", "calendar", show=False)

    def _file_for_view(self, key: str) -> Optional[File]:
        if key.startswith("gachas_"):
            return get_gacha_attachment()
        return None

    @app_commands.command(name="calendar", description="Want to stay up to date on events? Check out the calendar!")
    @app_commands.describe(private="Reply privately (default: True)")
    async def calendar(self, interaction: discord.Interaction, private: bool = True):
        if not private:
            channel_id = interaction.channel_id
            now = time.time()
            if self._public_cooldowns.get(channel_id, 0) > now:
                await interaction.response.send_message(
                    "# OOPS!\nGlobal features have a cooldown system to avoid spam...",
                    ephemeral=True,
                )
                return
            self._public_cooldowns[channel_id] = now + PUBLIC_COOLDOWN

        key = self.default_key
        view = self.cache.get(key)
        if view is None:
            await interaction.response.send_message(
                "Calendar cache is empty. Please wait a moment while it rebuilds.",
                ephemeral=True,
            )
            return

        file = self._file_for_view(key)
        if file:
            await interaction.response.send_message(view=view, file=file, ephemeral=private)
        else:
            await interaction.response.send_message(view=view, ephemeral=private)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return

        custom_id = interaction.data.get("custom_id", "")
        if not custom_id.startswith("schedule_"):
            return

        await interaction.response.defer()

        parts = custom_id.split("_")
        if len(parts) < 3:
            return

        action = parts[1]
        mode = parts[2]
        section_map = {
            "status": "status",
            "gachas": "gachas",
            "events": "events",
            "coming": "coming",
            "resets": "resets",
        }

        if action in section_map:
            key = f"{section_map[action]}_{mode}"
        else:
            key = self.default_key

        view = self.cache.get(key) or self.cache.get(self.default_key)
        if not view:
            return

        file = self._file_for_view(key)
        try:
            if file:
                await interaction.edit_original_response(view=view, attachments=[file])
            else:
                await interaction.edit_original_response(view=view, attachments=[])
        except Exception as e:
            log(f"[CALENDAR] edit_original_response error: {e}", "calendar", level="CRIT", show=False)
            await interaction.edit_original_response(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
    log("[COMMAND BUILDER]: /calendar", "slash", show=False)