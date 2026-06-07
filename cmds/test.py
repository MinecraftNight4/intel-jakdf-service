import discord
from discord import app_commands
from discord.ext import commands

private_guild = discord.Object(id=1332085001013039194)

class jakdfcmd_summon_cog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
    @app_commands.guilds(private_guild)
    @app_commands.command(name="potato", description="Saluda a un miembro")
    async def potato(self, interaction: discord.Interaction, member: str):
        await interaction.response.send_message(f"Hola {member}")


async def setup(bot):
    await bot.add_cog(jakdfcmd_summon_cog(bot))

