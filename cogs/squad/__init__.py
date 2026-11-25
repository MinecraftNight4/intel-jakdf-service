# cogs/squad/__init__.py
"""/squad account <1|4> [user]  ·  /squad roster <1|4>  ·  /squad editor <squadcode>  ·  /squad share <squadcode> [private]"""
import asyncio
import io
import re
import time
from typing import Dict, List, Optional

import discord
from discord import app_commands, ui
from discord.ext import commands
from logger import log

from cogs.calendar.helpers import PUBLIC_COOLDOWN
from cogs.profile.store import ProfileStore
from . import codec, image, render
from .build import ACCENT, DEFAULT_URL, BuilderView, State

OPEN_ID = "squad_open"
_CODE_RE = re.compile(r"squadcode=([A-Za-z0-9_-]+)")


def _texts(components):
    """Todos los textos de un mensaje de Components V2 (recorre contenedores y secciones)."""
    for comp in components or ():
        content = getattr(comp, "content", None)
        if isinstance(content, str):
            yield content
        yield from _texts(getattr(comp, "children", None))
        accessory = getattr(comp, "accessory", None)
        if accessory is not None:
            yield from _texts([accessory])


def extract_code(message) -> Optional[str]:
    """``squadcode`` del enlace ``[:](<url?squadcode=...>)`` de un mensaje, o None."""
    if message is None:
        return None
    for text in (*_texts(getattr(message, "components", None)), getattr(message, "content", "") or ""):
        found = _CODE_RE.search(text)
        if found:
            return found.group(1)
    return None


NO_UNITS = "{who} claimed any characters yet. Use `/profile edit` to add them."


def _channel_url(interaction: discord.Interaction) -> str:
    return getattr(interaction.channel, "jump_url", None) or DEFAULT_URL


def _text_view(text: str) -> ui.LayoutView:
    view = ui.LayoutView(timeout=None)
    box = ui.Container(accent_colour=ACCENT)
    box.add_item(ui.TextDisplay(text))
    view.add_item(box)
    return view


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
        state = State(interaction.user.id, count, pool, account.id if account else None,
                      url=_channel_url(interaction))
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
        await self._open_editor(interaction, squadcode)

    async def _open_editor(self, interaction: discord.Interaction, raw: str):
        """Responde al instante ("Reading build...") y luego abre el editor en el mismo mensaje."""
        shown = "".join((raw or "").replace("`", "").split())
        if shown.lower().startswith("squadcode:"):
            shown = shown[len("squadcode:"):]
        await interaction.response.send_message(
            view=_text_view(f"Reading build...\n-# `squadcode:{shown[:1500]}`"), ephemeral=True)
        try:
            build = codec.decode(raw)
        except codec.CodeError as err:
            await interaction.edit_original_response(view=_text_view(f"❌ {err}."))
            return
        pool = self._pool(build.account_id)
        if not pool:
            text = "The character list is empty." if build.account_id is None else \
                NO_UNITS.format(who=_nobody(build.account_id, interaction.user.id))
            await interaction.edit_original_response(view=_text_view(text))
            return
        known = {c["uuid"] for c in pool}             # con cuenta: solo las unidades que esa cuenta tiene
        slots, seen = [], set()
        for uuid in build.slots:
            keep = uuid in known and uuid not in seen
            slots.append(uuid if keep else 0)
            seen.add(uuid)
        state = State(interaction.user.id, len(slots), pool, build.account_id, slots, build.description,
                      url=_channel_url(interaction))
        await interaction.edit_original_response(view=BuilderView(state))

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

        await interaction.response.defer(ephemeral=private)      # dibujar la imagen puede tardar
        self.store.roster.reload_if_changed()
        by_uuid = self.store.roster.by_uuid
        code = codec.encode(build.creator_id, build.slots, build.account_id, build.description)
        none = discord.AllowedMentions.none()

        file = None
        try:
            creator = await self._username(build.creator_id)
            account = await self._username(build.account_id) if build.account_id else None
            data = image.build_data(build, by_uuid, creator or str(build.creator_id), account)
            png = await asyncio.to_thread(image.render_png, data)
            file = discord.File(io.BytesIO(png), filename="squad.png")
        except Exception as err:                                  # sin imagen: se comparte en texto
            log(f"[SQUAD]: share image failed: {type(err).__name__}: {err}", "squad", level="CRIT", show=False)

        # el mensaje lleva el codigo en el enlace del titulo: asi el boton lo lee del propio mensaje
        channel = interaction.channel
        url = getattr(channel, "jump_url", None) or DEFAULT_URL
        view = self._share_view(build, by_uuid, code, url, bool(file))
        kwargs = {"file": file} if file else {}
        await interaction.followup.send(view=view, ephemeral=private, allowed_mentions=none, **kwargs)
        if not private:                                           # ahora que existe, el enlace apunta al mensaje
            try:
                message = await interaction.original_response()
                await interaction.edit_original_response(
                    view=self._share_view(build, by_uuid, code, message.jump_url, bool(file)))
            except Exception as err:
                log(f"[SQUAD]: could not link the share message: {err}", "squad", level="WARN", show=False)

    def _share_view(self, build: codec.Build, by_uuid: Dict[int, dict], code: str, url: str, has_image: bool) -> ui.LayoutView:
        box = ui.Container(accent_colour=ACCENT)
        if has_image:
            gallery = ui.MediaGallery()
            gallery.add_item(media="attachment://squad.png")
            box.add_item(gallery)
        else:
            head = f"## Build made by <@{build.creator_id}>"
            if build.account_id:
                head += f"\n### <@{build.account_id}>'s character list"
            box.add_item(ui.TextDisplay(head + ("\n" + build.description if build.description else "")))
            box.add_item(ui.Separator())
            box.add_item(ui.TextDisplay(render.icons(build.slots, by_uuid, big=True)))
            box.add_item(ui.TextDisplay(render.slot_list(build.slots, by_uuid)))
        # texto discreto + boton; el ":" es un enlace escondido que lleva el codigo
        button = ui.Button(label="Edit", emoji="✏️", style=discord.ButtonStyle.primary, custom_id=OPEN_ID)
        box.add_item(ui.Section(
            ui.TextDisplay(f"-# You can edit this build by tapping here[:](<{url}?squadcode={code}>)"),
            accessory=button))
        view = ui.LayoutView(timeout=None)
        view.add_item(box)
        return view

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        """Boton "Open editor": el codigo se lee del enlace escondido del mensaje, sin cache (sirve tras reiniciar)."""
        if interaction.type != discord.InteractionType.component:
            return
        if (interaction.data or {}).get("custom_id") != OPEN_ID:
            return
        code = extract_code(interaction.message)
        if code is None:
            await interaction.response.send_message("❌ I couldn't read the build from this message.", ephemeral=True)
            return
        await self._open_editor(interaction, code)

    async def _username(self, user_id: int) -> Optional[str]:
        user = self.bot.get_user(user_id)
        if user is None:
            try:
                user = await self.bot.fetch_user(user_id)
            except Exception:
                return None
        return user.name


async def setup(bot: commands.Bot):
    await bot.add_cog(Squad(bot))
    log("[COMMAND BUILDER]: /squad", "slash", show=False)
