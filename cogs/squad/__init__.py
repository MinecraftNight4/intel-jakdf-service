# cogs/squad/__init__.py
"""/squad account <1|4> [user]  ·  /squad roster <1|4>  ·  /squad editor <squadcode>  ·  /squad share <squadcode> [private]"""
import time
from typing import Dict, List, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands
from logger import log

from cogs.calendar.helpers import PUBLIC_COOLDOWN
from cogs.profile.store import ProfileStore
from . import codec, render
from .build import ACCENT, BuilderView, State

NO_UNITS = "{who} claimed any characters yet. Use `/profile edit` to add them."


def _nobody(account_id: int, me: int) -> str:
    """Frase de "no tiene personajes" para la cuenta pedida."""
    return "You haven't" if account_id == me else f"<@{account_id}> hasn't"


class Squad(commands.GroupCog, name="squad"):
    account = app_commands.Group(name="account", description="Build a squad using a member's character list.")
    roster = app_commands.Group(name="roster", description="Build a squad using every character in the game.")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._store: Optional[ProfileStore] = None
        self._public_cooldowns: Dict[int, float] = {}
        super().__init__()

    @property
    def store(self) -> ProfileStore:
        """Misma base de datos que /profile (se reutiliza su instancia si ya esta cargada)."""
        if self._store is None:
            profile = self.bot.get_cog("Profile")
            self._store = getattr(profile, "store", None) or ProfileStore()
        return self._store

    # ---------------- reserva de unidades ----------------
    def _pool(self, account_id: Optional[int]) -> List[dict]:
        """Unidades elegibles: las de la cuenta indicada, o todo el roster."""
        roster = self.store.roster
        roster.reload_if_changed()
        if account_id is None:
            return list(roster.items)
        owned = self.store.owned(account_id)
        return [c for c in roster.items if c["uuid"] in owned]

    async def _open(self, interaction: discord.Interaction, count: int, account: Optional[discord.abc.User]):
        if account is not None and account.bot:
            await interaction.response.send_message("Bots don't play the game... yet.", ephemeral=True)
            return
        pool = self._pool(account.id if account else None)
        if not pool:
            text = "The character list is empty." if account is None else \
                NO_UNITS.format(who=_nobody(account.id, interaction.user.id))
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        state = State(interaction.user.id, count, pool, account.id if account else None)
        await interaction.response.send_message(view=BuilderView(state), ephemeral=True)

    # ---------------- /squad account ----------------
    @account.command(name="4", description="Create a Squad of 4 characters using a member's character list.")
    @app_commands.describe(user="Whose character list to use (default: yours)")
    async def account_1(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        await self._open(interaction, 4, user or interaction.user)

    @account.command(name="16", description="Create a Squad of 16 characters using a member's character list.")
    @app_commands.describe(user="Whose character list to use (default: yours)")
    async def account_4(self, interaction: discord.Interaction, user: Optional[discord.User] = None):
        await self._open(interaction, 16, user or interaction.user)

    # ---------------- /squad roster ----------------
    @roster.command(name="4", description="Create a Squad of 4 characters using all the characters.")
    async def roster_1(self, interaction: discord.Interaction):
        await self._open(interaction, 4, None)

    @roster.command(name="16", description="Create a Squad of 16 characters using all the characters.")
    async def roster_4(self, interaction: discord.Interaction):
        await self._open(interaction, 16, None)

    # ---------------- /squad editor ----------------
    @app_commands.command(name="editor", description="Load a squad code into the builder to keep editing it.")
    @app_commands.describe(squadcode="The code of the build (from /squad share or the builder)")
    async def editor(self, interaction: discord.Interaction, squadcode: str):
        try:
            build = codec.decode(squadcode)
        except codec.CodeError as err:
            await interaction.response.send_message(f"❌ {err}.", ephemeral=True)
            return
        pool = self._pool(build.account_id)
        if not pool:
            text = "The character list is empty." if build.account_id is None else \
                NO_UNITS.format(who=_nobody(build.account_id, interaction.user.id))
            await interaction.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
            return
        known = {c["uuid"] for c in pool}             # con cuenta: solo las unidades que esa cuenta tiene
        slots, seen = [], set()
        for uuid in build.slots:
            keep = uuid in known and uuid not in seen
            slots.append(uuid if keep else 0)
            seen.add(uuid)
        state = State(interaction.user.id, len(slots), pool, build.account_id, slots, build.description)
        await interaction.response.send_message(view=BuilderView(state), ephemeral=True)

    # ---------------- /squad share ----------------
    @app_commands.command(name="share", description="Show a build from its squad code.")
    @app_commands.describe(squadcode="The code of the build", private="Reply privately (default: False)")
    async def share(self, interaction: discord.Interaction, squadcode: str, private: bool = False):
        try:
            build = codec.decode(squadcode)
        except codec.CodeError as err:
            await interaction.response.send_message(f"❌ {err}.", ephemeral=True)
            return
        if not private:
            now, channel = time.time(), interaction.channel_id
            if self._public_cooldowns.get(channel, 0) > now:
                await interaction.response.send_message(
                    "# OOPS!\nGlobal features have a cooldown system to avoid spam...", ephemeral=True)
                return
            self._public_cooldowns[channel] = now + PUBLIC_COOLDOWN

        self.store.roster.reload_if_changed()
        by_uuid = self.store.roster.by_uuid
        head = f"## Build made by <@{build.creator_id}>"
        if build.account_id:
            head += f"\n### <@{build.account_id}>'s character list"

        box = ui.Container(accent_colour=ACCENT)
        box.add_item(ui.TextDisplay(head + ("\n" + build.description if build.description else "")))
        box.add_item(ui.Separator())
        box.add_item(ui.TextDisplay(render.icons(build.slots, by_uuid, big=True)))
        box.add_item(ui.TextDisplay(render.names(build.slots, by_uuid)))
        box.add_item(ui.TextDisplay(f"||```/squad editor squadcode:{codec.encode(build.creator_id, build.slots, build.account_id, build.description)}```||"))
        view = ui.LayoutView(timeout=None)
        view.add_item(box)
        await interaction.response.send_message(view=view, ephemeral=private,
                                                allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(Squad(bot))
    log("[COMMAND BUILDER]: /squad", "slash", show=False)
