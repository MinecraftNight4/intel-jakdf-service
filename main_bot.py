import os
import discord
from dotenv import load_dotenv
from discord.ext import commands

load_dotenv()
intents = discord.Intents.all()
private_guild = discord.Object(id=1332085001013039194)
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.command(name="reload")
@commands.is_owner()  # solo el dueño del bot
async def reload(ctx, extension: str):
    try:
        await bot.reload_extension(f"cogs.{extension}")
        await ctx.send(f"✅ Cog `{extension}` recargado correctamente.")
    except Exception as e:
        await ctx.send(f"❌ Error al recargar: `{e}`")


@bot.event
async def on_ready():
    extensions = [
        "cogs.news",          # ← Solo necesitas crear esta carpeta
    ]
    
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Cargado: {ext}")
        except Exception as e:
            print(f"❌ Error al cargar {ext}: {e}")

    await bot.tree.sync()
    print(f"Bot listo como {bot.user} | Comandos sincronizados")

bot.run(os.getenv("DISCORDTOKEN"))