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
    # Carga solo los cogs que sí tienes por ahora
    extensions = [
        "cmds.kaiju_news",     # ← el que te di
        # "cmds.summon",       # ← coméntalo o elimínalo
        # "cmds.otro",         # comenta los que no existan
    ]
    
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Cargado: {ext}")
        except Exception as e:
            print(f"❌ Error al cargar {ext}: {e}")

    await bot.tree.sync(guild=private_guild)
    print(f"Bot listo como {bot.user} | Comandos sincronizados")

bot.run(os.getenv("DISCORDTOKEN"))