import discord

from typing import Optional
from discord.ext import commands
from discord import app_commands, ui
from logger import log

import feed_store
from feed_store import MAX_FEEDS_PER_GUILD
from feed_store import load as load_feeds  # main.py lo importa para leer allow_feed_commands

FEED_TYPES = {
    "feed_game_general": "Game news | All the news",
    "feed_game_gacha": "Game news | Only Gachas",
    "feed_game_event": "Game news | Only Events",
    "feed_game_service": "Game news | Only Updates",
    "feed_game_store": "Webstore | Shop items",
    "xcom-kaijuno8_o_en": "x.com | (EN) @kaijuno8_o_en",
    "xcom-kaijuno8_o": "x.com | (JP) @kaijuno8_o",
    "xcom-kj8_thegame_en": "x.com | (EN) @kj8_thegame_en",
    "xcom-kj8_thegame": "x.com | (JP) @kj8_thegame",
}

VIEW_TEXT_LIMIT = 3800   # Discord permite 4000 caracteres de texto por mensaje
PREVIEW_CHARS = 80


class FeedViewLayout(ui.LayoutView):
    def __init__(self, content: str):
        super().__init__()
        container = ui.Container(accent_colour=0xFF8C00)
        container.add_item(ui.TextDisplay("## 📡 Feed Configuration"))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(content))
        self.add_item(container)


def _channel_label(guild: discord.Guild, channel_id: int) -> str:
    channel = guild.get_channel(int(channel_id))
    return f"#{channel.name}" if channel else f"deleted channel ({channel_id})"


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= PREVIEW_CHARS else flat[:PREVIEW_CHARS - 1] + "…"


class Feeds(commands.GroupCog, name="feed"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

    # ============================================================
    # /feed setup
    # ============================================================
    @app_commands.command(name="setup", description="Once the bot detects new content, will send it!")
    @app_commands.describe(
        feed_type=f"Select the type of feed. (Up to {MAX_FEEDS_PER_GUILD} feeds per server, repeating types is allowed)",
        channel="Select the channel to send updates. (Requires: Send Message, Attach Files & Link Embed)",
        publish="Setup if the bot can cross-post in a newschannel (Requires: Manage Message)",
        text="Set a custom ping message. (use \\n for new lines, max 1000 chars)",
    )
    @app_commands.choices(
        feed_type=[
            app_commands.Choice(name=name, value=value)
            for value, name in FEED_TYPES.items()
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def setup(
        self,
        interaction: discord.Interaction,
        feed_type: app_commands.Choice[str],
        channel: discord.TextChannel,
        publish: bool = False,
        text: Optional[str] = None,
    ):
        feed_id = feed_type.value
        feed_string = feed_type.name
        guild_id = interaction.guild.id

        # Límite por servidor (se revisa ANTES de enviar el mensaje de prueba)
        if feed_store.would_exceed_limit(guild_id, feed_id, channel.id):
            await interaction.response.send_message(
                f"## 📢 __FEED LIMIT!__ ⚠️\nThis server already uses **{MAX_FEEDS_PER_GUILD}/{MAX_FEEDS_PER_GUILD}** feeds.\n"
                "> Remove one with `/feed clear` before adding a new one.",
                ephemeral=True,
            )
            return

        # Mensaje de prueba
        test_embed = discord.Embed(
            description=f"## 📢 __FEED SETUP!__ ℹ️\nThis channel now will post content related to **{feed_string}**",
        )
        try:
            await channel.send(embed=test_embed)
        except Exception:
            await interaction.response.send_message(
                "## 📢 __FEED ERROR!__ ⚠️\n- The bot is not able to post in the selected channel!\n> Make sure to allow `send message`, `allow attachments` and `manage messages` to the bot.",
                ephemeral=True,
            )
            return

        result, total = feed_store.add_or_update(guild_id, feed_id, channel.id, publish, text)

        if result == "limit":
            # Carrera poco probable: otro admin llenó el cupo entre la revisión y el guardado.
            await interaction.response.send_message(
                f"## 📢 __FEED LIMIT!__ ⚠️\nThis server already uses **{MAX_FEEDS_PER_GUILD}/{MAX_FEEDS_PER_GUILD}** feeds.",
                ephemeral=True,
            )
            return

        title = "FEED ENABLED!" if result == "added" else "FEED UPDATED!"
        await interaction.response.send_message(
            f"## 📢 __{title}__ ✅\n- {channel.mention} will post about **`{feed_string}`**.\n"
            f"-# Feeds in use: {total}/{MAX_FEEDS_PER_GUILD}",
            ephemeral=True,
        )

    # ============================================================
    # /feed clear
    # ============================================================
    @app_commands.command(name="clear", description="Remove one of this server's feeds.")
    @app_commands.describe(feed="The feed to remove (pick one from the list)")
    @app_commands.default_permissions(administrator=True)
    async def clear(self, interaction: discord.Interaction, feed: str):
        guild = interaction.guild

        feed_id, _, channel_raw = feed.rpartition(":")
        if not feed_id or not channel_raw.isdigit():
            await interaction.response.send_message(
                "❌ Please pick a feed from the list.", ephemeral=True
            )
            return

        removed = feed_store.remove(guild.id, feed_id, int(channel_raw))
        if not removed:
            await interaction.response.send_message(
                "❌ That feed is not active in this server (maybe it was already removed).",
                ephemeral=True,
            )
            return

        feed_string = FEED_TYPES.get(feed_id, feed_id)
        remaining = len(feed_store.guild_entries(guild.id))
        await interaction.response.send_message(
            f"## 📢 __FEED DISABLED!__ 🚫\n- `{feed_string}` will no longer post in {_channel_label(guild, int(channel_raw))}.\n"
            f"-# Feeds in use: {remaining}/{MAX_FEEDS_PER_GUILD}",
            ephemeral=True,
        )

    @clear.autocomplete("feed")
    async def clear_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        guild = interaction.guild
        if guild is None:
            return []

        current = current.lower()
        choices: list[app_commands.Choice[str]] = []
        for entry in feed_store.guild_entries(guild.id):
            feed_id = entry.get("type", "")
            channel_id = entry.get("channel")
            label = f"{FEED_TYPES.get(feed_id, feed_id)} → {_channel_label(guild, channel_id)}"
            if current and current not in label.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=f"{feed_id}:{channel_id}"))
        return choices[:25]

    # ============================================================
    # /feed view
    # ============================================================
    @app_commands.command(name="view", description="Displays a panel with the current feed settings.")
    @app_commands.default_permissions(administrator=True)
    async def view(self, interaction: discord.Interaction):
        guild = interaction.guild
        entries = feed_store.guild_entries(guild.id)

        lines = [f"**Feeds in use:** {len(entries)}/{MAX_FEEDS_PER_GUILD}"]

        if not entries:
            lines.append("-# No feeds configured. Use `/feed setup` to add one.")

        # Agrupado por tipo, en el orden de FEED_TYPES
        for feed_id, feed_string in FEED_TYPES.items():
            group = [e for e in entries if e.get("type") == feed_id]
            if not group:
                continue

            block = [f"**{feed_string}**"]
            for entry in group:
                channel_id = entry.get("channel")
                mention = f"<#{channel_id}>" if channel_id else "`Unknown`"
                publish_str = "Yes" if entry.get("publish") else "No"
                line = f"- {mention} | Can publish: {publish_str}"
                if entry.get("text"):
                    line += f"\n  -# Ping: {_preview(entry['text'])}"
                block.append(line)
            lines.append("\n".join(block))

        content = "\n\n".join(lines)
        if len(content) > VIEW_TEXT_LIMIT:
            content = content[:VIEW_TEXT_LIMIT - 1].rstrip() + "…"

        await interaction.response.send_message(view=FeedViewLayout(content), ephemeral=True)


async def setup(bot: commands.Bot):
    log(f"[COMMAND BUILDER]: /FEED", "slash", show=False)
    allowed = []
    data_guilds = load_feeds().get("allow_feed_commands", [])

    for guild_uuid in data_guilds:
        try:
            guild = discord.Object(id=int(guild_uuid))
            allowed.append(guild)
            log(f"- [{guild_uuid}] ✅", "slash", show=False)
        except (ValueError, TypeError):
            log(f"- [{guild_uuid}] ❌", "slash", level="WARN", show=False)
    log(f"[COMMAND BUILDER]: /FEED | [x{len(data_guilds)} GUILD(S) LISTED] [x{len(allowed)} GUILD(S) ALLOWED]", "slash", show=False)

    await bot.add_cog(Feeds(bot), guilds=allowed)
    log(f"[COMMAND BUILDER]: /FEED (Thread closed!)", "slash", show=False)
    log(f" ", "slash", show=False)
