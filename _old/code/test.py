import os
import discord
from discord import ui
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
intents = discord.Intents.all()
private_guild = discord.Object(id=1332085001013039194)
bot = commands.Bot(command_prefix=".", intents=intents)

class MenuLayout(ui.LayoutView):
    def __init__(self):
        super().__init__()
        container = ui.Container(ui.TextDisplay("LOREM IPSUN"))
        self.add_item(container)
    


@bot.command()
async def test(ctx:commands.Context):
    layout = MenuLayout()
    await ctx.reply(view=layout)



bot.run(os.getenv("DISCORDTOKEN"))