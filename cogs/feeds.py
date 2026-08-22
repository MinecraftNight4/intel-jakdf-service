import json
import os
import discord

from typing import Optional
from discord.ext import commands
from discord import app_commands, ui
from logger import info, warn, crit, log

FEEDS_FILE = "sys_save/feed_system_setup.json"

FEED_TYPES = {
    "feed_game_all": "Game news | All the news",
    "feed_game_gacha": "Game news | Only gachas",
    "feed_game_event": "Game news | Only events",
    "feed_game_patch": "Game news | Only updates",
    "xcom-kaijuno8_o_en": "x.com | (EN) @kaijuno8_o_en",
    "xcom-kaijuno8_o": "x.com | (JP) @kaijuno8_o",
    "xcom-kj8_thegame_en": "x.com | (EN) @kj8_thegame_en",
    "xcom-kj8_thegame": "x.com | (JP) @kj8_thegame"
}


def load_feeds() -> dict:
    if not os.path.exists(FEEDS_FILE):
        return {"allow_feed_commands": []}
    try:
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "allow_feed_commands" not in data:
            data["allow_feed_commands"] = []
        return data
    except Exception:
        return {"allow_feed_commands": []}


def save_feeds(data: dict):
    os.makedirs(os.path.dirname(FEEDS_FILE), exist_ok=True)
    with open(FEEDS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class FeedViewLayout(ui.LayoutView):
    def __init__(self, content: str):
        super().__init__()
        container = ui.Container(accent_colour=0xFF8C00)
        container.add_item(ui.TextDisplay("## 📡 Feed Configuration"))
        container.add_item(ui.Separator())
        container.add_item(ui.TextDisplay(content))
        self.add_item(container)


class Feeds(commands.GroupCog, name="feed"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        super().__init__()

# ============================================================
# Dentro de la clase Feeds → comando setup
# ============================================================
    @app_commands.command(name="setup", description="Setup a feed type in a channel.")
    @app_commands.describe(
        feed_type="Select the type of feed to track.",
        channel="Select a channel to post.",
        publish="Allow cross-posting? (Defalt: False | Only for News Channels)",
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
        guild_id = str(interaction.guild.id)

        # Mensaje de prueba
        test_embed = discord.Embed(
            description=f"## 📢 __FEED SETUP!__ ℹ️\nThis channel now will post content related to **{feed_string}**.",
            
        )
        try:
            await channel.send(embed=test_embed)
        except Exception:
            await interaction.response.send_message(
                "## 📢 __FEED ERROR!__ ⚠️\n- The bot is not able to post in the selected channel!\n> Make sure to allow `send message`, `allow attachments` and `manage messages` to the bot.",
                ephemeral=True,
            )
            return
        
        # ---------- GUARDAR EN FORMATO ANIDADO ----------
        data = load_feeds()

        if feed_id not in data:
            data[feed_id] = {}
        entry = {
            "channel": channel.id,
            "publish": bool(publish),
        }
        if text and text.strip():
            entry["text"] = text.replace("\\n", "\n")[:1000]
        else:
            entry.pop("text", None)

        data[feed_id][guild_id] = entry
        save_feeds(data)
        await interaction.response.send_message(
            f"## 📢 __FEED ENABLED!__ ✅\n- {channel.mention} will post about **`{feed_string}`**.",
            ephemeral=True,
        )

    # ============================================================
    # Comando clear
    # ============================================================
    @app_commands.command(name="clear", description="Disable a feed type from this server.")
    @app_commands.describe(
        feed_type="Type of feed to disable",
    )
    @app_commands.choices(
        feed_type=[
            app_commands.Choice(name=name, value=value)
            for value, name in FEED_TYPES.items()
        ]
    )
    @app_commands.default_permissions(administrator=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        feed_type: app_commands.Choice[str]
    ):
        feed_id = feed_type.value
        feed_string = feed_type.name
        guild_id = str(interaction.guild.id)

        data = load_feeds()

        if feed_id in data and guild_id in data[feed_id]:
            del data[feed_id][guild_id]

            if not data[feed_id]:
                del data[feed_id]

            save_feeds(data)

        await interaction.response.send_message(
            f"## 📢 __FEED DISABLED!__ 🚫\n- `{feed_string}` is not longer active in this server.",
            ephemeral=True,
        )

    # ============================================================
    # Comando view
    # ============================================================
    @app_commands.command(name="view", description="Check the status of feeds in this server.")
    @app_commands.default_permissions(administrator=True)
    async def view(self, interaction: discord.Interaction):
        guild_id = str(interaction.guild.id)
        data = load_feeds()

        lines = []
        for feed_id, feed_string in FEED_TYPES.items():
            entry = data.get(feed_id, {}).get(guild_id)

            if not entry:
                lines.append(f"**{feed_string}**\n- Not configured")
                continue

            channel_id = entry.get("channel")
            can_publish = entry.get("publish", False)
            text = entry.get("text")

            channel_mention = f"<#{channel_id}>" if channel_id else "`Unknown`"
            publish_str = "Yes" if can_publish else "No"

            block = (
                f"**{feed_string}**\n"
                f"- Channel: {channel_mention} | Can publish: {publish_str}"
            )
            if text is not None:
                block += f"\n- Ping message:\n{text}"

            lines.append(block)

        content = "\n\n".join(lines) if lines else "No feed types available."
        view = FeedViewLayout(content)
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    data = load_feeds()
    allowed = [discord.Object(id=int(gid)) for gid in data.get("allow_feed_commands", [])]

    # Cargamos el cog SOLO en las guilds autorizadas
    await bot.add_cog(Feeds(bot), guilds=allowed)
    log("WARN", "Algo raro pasó", show=False)
    
    print(f"✅ /feed cargado solo en {len(allowed)} guild(s): {[g.id for g in allowed]}")