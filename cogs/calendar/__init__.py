# cogs/calendar/__init__.py
import time
from typing import Dict

import discord
from discord import app_commands, ui
from discord.ext import commands
from logger import log

from .helpers import PUBLIC_COOLDOWN, has_active_maintenance
from .update import build_update_view
from .gacha import build_gacha_view
from .event import build_event_view
from .soon import build_soon_view
from .misc import build_misc_view


class Calendar(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: Dict[str, ui.LayoutView] = {}
        self.default_key = "gacha_abs"
        self._public_cooldowns: Dict[int, float] = {}
        self.rebuild_calendar_cache()

    def rebuild_calendar_cache(self):
        log("[CALENDAR]: Rebuilding cache...", "calendar", show=False)

        self.cache["update_abs"] = build_update_view(relative=False)
        self.cache["update_rel"] = build_update_view(relative=True)

        self.cache["gacha_abs"]  = build_gacha_view(relative=False)
        self.cache["gacha_rel"]  = build_gacha_view(relative=True)

        self.cache["event_abs"]  = build_event_view(relative=False)
        self.cache["event_rel"]  = build_event_view(relative=True)

        self.cache["soon_abs"]   = build_soon_view(relative=False)
        self.cache["soon_rel"]   = build_soon_view(relative=True)

        self.cache["misc_abs"]   = build_misc_view(relative=False)
        self.cache["misc_rel"]   = build_misc_view(relative=True)

        self.default_key = "update_abs" if has_active_maintenance() else "gacha_abs"
        log(f"[CALENDAR]: Cache rebuilt → default: {self.default_key}", "calendar", show=False)

    @app_commands.command(name="calendar", description="Tick-Tack! Don't miss the upcoming schedules...")
    @app_commands.describe(private="Reply privately (default: True)")
    async def calendar(self, interaction: discord.Interaction, private: bool = True):
        if not private:
            channel_id = interaction.channel_id
            now = time.time()
            if self._public_cooldowns.get(channel_id, 0) > now:
                await interaction.response.send_message(
                    "# OOPS!\nGlobal features have a cooldown system to avoid spam...",
                    ephemeral=True
                )
                return
            self._public_cooldowns[channel_id] = now + PUBLIC_COOLDOWN

        view = self.cache.get(self.default_key)
        if view is None:
            await interaction.response.send_message(
                "Calendar cache is empty. Please wait a moment while it rebuilds.",
                ephemeral=True
            )
            return

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
        mode   = parts[2]

        section_map = {
            "update": "update",
            "banner": "gacha",
            "event":  "event",
            "maps":   "soon",
            "misc":   "misc",
        }

        if action == "toggle":
            section = parts[2] if len(parts) > 3 else "gacha"
            new_mode = parts[3] if len(parts) > 3 else ("rel" if mode == "abs" else "abs")
            key = f"{section}_{new_mode}"
        else:
            section = section_map.get(action, "gacha")
            key = f"{section}_{mode}"

        view = self.cache.get(key) or self.cache.get(self.default_key)
        if view:
            await interaction.edit_original_response(view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Calendar(bot))
    log("[COMMAND BUILDER]: /calendar", "slash", show=False)