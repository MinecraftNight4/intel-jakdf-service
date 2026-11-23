# cogs/profile/__init__.py
"""/profile view [user] [private]  ·  /profile claim <character> <status>"""
import time
from typing import Dict, List, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands
from logger import log

from cogs.calendar.helpers import PUBLIC_COOLDOWN
from .store import LOCKED, MAX_DUPES, ProfileStore

PER_PAGE = 20
ACCENT = 0x43D7D7

STATUS_CHOICES = [
    app_commands.Choice(name="🔒 Locked character (remove it)", value=LOCKED),
    app_commands.Choice(name="✅ Unlocked, no dupes", value=0),
    *[
        app_commands.Choice(name=f"+{n} dupe{'s' if n > 1 else ''}" + (" (MAX)" if n == MAX_DUPES else ""), value=n)
        for n in range(1, MAX_DUPES + 1)
    ],
]


def _line(name: str, dupes: int) -> str:
    return f"`+{dupes}` {name}" + (" ⭐" if dupes >= MAX_DUPES else "")


class ProfileView(ui.LayoutView):
    """Una pagina del perfil. Los botones (solo para quien ejecuto el comando) cambian de pagina."""

    def __init__(self, owner_id: int, target: discord.abc.User, entries: List[tuple],
                 total: int, page: int = 0):
        super().__init__(timeout=300)
        self.owner_id, self.target, self.entries, self.total = owner_id, target, entries, total
        pages = max(1, -(-len(entries) // PER_PAGE))
        self.page = min(max(page, 0), pages - 1)

        dupes = sum(d for _, d in entries)
        head = (
            f"## 🪪 __PROFILE__ · {target.display_name}\n"
            f"-# {len(entries)}/{total} characters unlocked · {dupes} dupes in total"
        )
        chunk = entries[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        body = "\n".join(_line(n, d) for n, d in chunk) or "*No characters claimed yet. Use `/profile claim`.*"

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
        await interaction.response.send_message("Run `/profile view` yourself to browse a profile.", ephemeral=True)
        return False

    async def _go(self, interaction: discord.Interaction, step: int):
        view = ProfileView(self.owner_id, self.target, self.entries, self.total, self.page + step)
        await interaction.response.edit_message(view=view)


class Profile(commands.GroupCog, name="profile"):
    # Scheduler (ver main.py → _register_refreshers): aprende personajes nuevos de las noticias.
    REFRESH_KEY = "embed_profile"
    REFRESH_LABEL = "Updating Characters"
    REFRESH_ETA = 1

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.store = ProfileStore()
        self._public_cooldowns: Dict[int, float] = {}
        super().__init__()

    def refresh_cache(self):
        added = self.store.learn_from_news()
        if added:
            log(f"[PROFILE]: {added} new character(s) added to the roster", "profile", show=False)

    # ---------------- /profile view ----------------
    @app_commands.command(name="view", description="See the characters (and dupes) you or another user have unlocked.")
    @app_commands.describe(user="Whose profile to see (default: yours)", private="Reply privately (default: True)")
    async def view(self, interaction: discord.Interaction, user: Optional[discord.User] = None, private: bool = True):
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
        entries = list(self.store.get(target.id).items())
        view = ProfileView(interaction.user.id, target, entries, total=len(self.store.roster))
        await interaction.response.send_message(view=view, ephemeral=private)

    # ---------------- /profile claim ----------------
    @app_commands.command(name="claim", description="Set whether you own a character and how many dupes it has.")
    @app_commands.describe(character="Character to update", status="Locked, unlocked, or how many dupes (up to 6)")
    @app_commands.choices(status=STATUS_CHOICES)
    async def claim(self, interaction: discord.Interaction, character: str, status: app_commands.Choice[int]):
        name = self.store.resolve(character)
        if name is None:
            await interaction.response.send_message(
                "## ❌ Unknown character\nPick one from the list that appears while typing.", ephemeral=True)
            return
        self.store.set_status(interaction.user.id, name, status.value)
        log(f"[PROFILE] user={interaction.user.id} {name} → {status.value}", "profile", show=False)
        await interaction.response.send_message(f"✅ **{name}** → {status.name}", ephemeral=True)

    @claim.autocomplete("character")
    async def claim_character_autocomplete(self, interaction: discord.Interaction, current: str):
        return [app_commands.Choice(name=n[:100], value=n) for n in self.store.search(current)]


async def setup(bot: commands.Bot):
    await bot.add_cog(Profile(bot))
    log("[COMMAND BUILDER]: /profile", "slash", show=False)
