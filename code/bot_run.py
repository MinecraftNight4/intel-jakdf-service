import os
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
intents = discord.Intents.all()
private_guild = discord.Object(id=1332085001013039194)
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    await bot.load_extension("cmds.summon")
    await bot.tree.sync(guild=private_guild)

bot.run(os.getenv("DISCORDTOKEN"))