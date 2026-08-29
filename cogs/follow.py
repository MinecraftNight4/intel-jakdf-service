import json
import os
import discord
from discord import app_commands
from discord.ext import commands
from logger import log

FOLLOW_FILE = "sys_save/feed_system_follow.json"


def load_follow_sources() -> dict:
    if not os.path.exists(FOLLOW_FILE):
        return {}
    try:
        with open(FOLLOW_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


class Follow(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="follow",
        description="Subscribe this server to an official news feed channel."
    )
    @app_commands.describe(
        feed_type="Type of feed to follow",
        channel="Channel where the news will be posted",
    )
    @app_commands.default_permissions(manage_webhooks=True)
    @app_commands.guild_only()
    async def follow(
        self,
        interaction: discord.Interaction,
        feed_type: str,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)

        sources = load_follow_sources()
        source = sources.get(feed_type)

        if not source:
            await interaction.followup.send("## ❌ Unknown or unconfigured feed type.", ephemeral=True)
            return

        # Permisos del bot en el canal destino
        perms = channel.permissions_for(channel.guild.me)
        if not perms.manage_webhooks:
            await interaction.followup.send(
                "## 📢 __FOLLOW ERROR!__ ⚠️\nThe bot requires the permission `Manage Webhooks` to run the command.",
                ephemeral=True,
            )
            return

        # Canal fuente
        try:
            source_channel = self.bot.get_channel(int(source["channel_id"]))
            if source_channel is None:
                source_channel = await self.bot.fetch_channel(int(source["channel_id"]))
        except Exception:
            await interaction.followup.send(
                "## 📢 __FOLLOW ERROR!__ 🔥\nKaijus are jamming our connection!!\n-# `error_follow_not_listed`",
                ephemeral=True,
            )
            return
        if not getattr(source_channel, "is_news", lambda: False)():
            await interaction.followup.send(
                "## 📢 __FOLLOW ERROR!__ 🔥\nKaijus are jamming our connection!!\n-# `error_follow_invalid_type`",
                ephemeral=True,
            )
            return

        # Follow nativo de Discord
        
        if getattr(channel, "is_news", lambda: False)():
            await interaction.followup.send(
                f"## 📢 __FOLLOW ERROR!__ ⚠️\n{channel.mention} is a **NEWS CHANNEL**.\nDiscord doens't allow News Channel to follow other News Channels!",
                ephemeral=True,
                )
            return
        try:
            await source_channel.follow(
                destination=channel,
                reason=f"/follow | By: {interaction.user} ({interaction.user.id})"
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "## 📢 __FOLLOW ERROR!__ ⚠️\nDiscord blocked this action. Maybe I lack permissions to perform this action...",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await interaction.followup.send(
                f"## 📢 __FOLLOW ERROR!__ ⚠️\nDiscord lend a communication error...\n```{e}```",
                ephemeral=True,
            )
            return

        name = source.get("name", feed_type)
        await interaction.followup.send(
            f"## 📢 __FOLLOW SETUP!__ ℹ️\nNow {channel.mention} will be updated with content related to `{name}`.",
            ephemeral=True,
        )
        log(f"[FOLLOW] guild={interaction.guild.id} feed={feed_type} → #{channel.id}", "follow", show=False)


    # Autocompletado dinámico desde el JSON
    @follow.autocomplete("feed_type")
    async def feed_type_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        sources = load_follow_sources()
        current = current.lower()
        choices = []
        for key, data in sources.items():
            name = data.get("name", key)
            if current in name.lower() or current in key.lower():
                choices.append(app_commands.Choice(name=name, value=key))
            if len(choices) >= 25:
                break
        return choices


async def setup(bot: commands.Bot):
    await bot.add_cog(Follow(bot))