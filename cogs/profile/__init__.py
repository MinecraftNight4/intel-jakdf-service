# cogs/profile/__init__.py
"""/profile display [user] [private]  ·  /profile edit"""
import asyncio
import time
from typing import Dict, List, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands, tasks
from logger import log

from cogs.calendar.helpers import PUBLIC_COOLDOWN
from .bulk import BulkView
from .format import stars
from .store import INACTIVE_DAYS, ProfileStore

PER_PAGE = 20
ACCENT = 0x43D7D7

def _line(icon: str, name: str, dupes: int) -> str:
    return f"{stars(dupes)} {icon} {name}"


class ProfileView(ui.LayoutView):
    """Una pagina del perfil. Los botones (solo para quien ejecuto el comando) cambian de pagina."""

    def __init__(self, owner_id: int, target: discord.abc.User, entries: List[tuple],
                 total: int, updated_at: Optional[int] = None, page: int = 0):
        """``entries``: [(personaje, dupes)] ya ordenado."""
        super().__init__(timeout=300)
        self.owner_id, self.target, self.entries, self.total = owner_id, target, entries, total
        self.updated_at = updated_at
        pages = max(1, -(-len(entries) // PER_PAGE))
        self.page = min(max(page, 0), pages - 1)

        dupes = sum(d for _, d in entries)
        head = (
            f"## 🪪 __PROFILE__ · {target.display_name.upper()}\n"
            f"`{len(entries)}/{total}` characters unlocked"
        )
        if updated_at:
            head += f"\n\n-# 🗑️ Profiles are removed after 1 year of inactivity.\n-#  `⤷` ⌛ Scheduled for removed <t:{updated_at + 31556926 }:R>."
        chunk = entries[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        body = "\n".join(_line(c["icon"], c["name"], d) for c, d in chunk) or "*No characters claimed yet. Use `/profile edit`.*"

        box = ui.Container(accent_colour=ACCENT)
        box.add_item(ui.TextDisplay(head))
        box.add_item(ui.Separator())
        box.add_item(ui.TextDisplay(body))
        if pages > 1:
            box.add_item(ui.Separator())
            row = ui.ActionRow()
            prev = ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
            nxt = ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= pages - 1)
            prev.callback = lambda i: self._go(i, -1)
            nxt.callback = lambda i: self._go(i, +1)
            row.add_item(prev)
            row.add_item(ui.Button(label=f"{self.page + 1}/{pages}", style=discord.ButtonStyle.primary, disabled=True))
            row.add_item(nxt)
            box.add_item(row)
        self.add_item(box)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True
        await interaction.response.send_message("Run `/profile display` yourself to browse a profile.", ephemeral=True)
        return False

    async def _go(self, interaction: discord.Interaction, step: int):
        view = ProfileView(self.owner_id, self.target, self.entries, self.total, self.updated_at, self.page + step)
        await interaction.response.edit_message(view=view)


class Profile(commands.GroupCog, name="profile"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = ProfileStore()
        self._public_cooldowns: Dict[int, float] = {}
        super().__init__()

    async def cog_load(self):
        self.prune_loop.start()

    async def cog_unload(self):
        self.prune_loop.cancel()

    @tasks.loop(hours=24)
    async def prune_loop(self):
        removed = await asyncio.to_thread(self.store.prune)
        if removed:
            log(f"[PROFILE]: {removed} inactive profile(s) deleted", "profile", show=False)

    # ---------------- /profile display ----------------
    @app_commands.command(name="display", description="See the characters (and dupes) you or another user have unlocked.")
    @app_commands.describe(user="Whose profile to see (default: yours)", private="Reply privately (default: True)")
    async def display(self, interaction: discord.Interaction, user: Optional[discord.User] = None, private: bool = True):
        if not private:
            now, channel = time.time(), interaction.channel_id
            if self._public_cooldowns.get(channel, 0) > now:
                await interaction.response.send_message(
                    "# OOPS!\nGlobal features have a cooldown system to avoid spam...", ephemeral=True)
                return
            self._public_cooldowns[channel] = now + PUBLIC_COOLDOWN

        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message("Bots don't play the game... yet.", ephemeral=True)
            return
        entries, updated_at = self.store.get(target.id)
        view = ProfileView(interaction.user.id, target, entries, len(self.store.roster.items), updated_at)
        await interaction.response.send_message(view=view, ephemeral=private)

    # ---------------- /profile edit ----------------
    @app_commands.command(name="edit", description="Edit your characters and dupes with a private panel.")
    async def edit(self, interaction: discord.Interaction):
        await interaction.response.send_message(view=BulkView(self.store, interaction.user.id), ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
    log("[COMMAND BUILDER]: /profile", "slash", show=False)
