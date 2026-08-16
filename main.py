"""
Punto de entrada único del servicio.
1. Arranca todos los timers de /timer/
2. Luego inicia el bot de Discord
"""
import os
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import start_all_timers, set_rebuild_callback

load_dotenv()

intents = discord.Intents.all()
private_guild = discord.Object(id=1332085001013039194)
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.command(name="reload")
@commands.is_owner()
async def reload(ctx, extension: str):
    try:
        await bot.reload_extension(f"cogs.{extension}")
        await ctx.send(f"✅ Cog `{extension}` recargado correctamente.")
    except Exception as e:
        await ctx.send(f"❌ Error al recargar: `{e}`")


@bot.event
async def on_ready():
    extensions = [
        "cogs.news",
    ]

    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Cargado: {ext}")
        except Exception as e:
            print(f"❌ Error al cargar {ext}: {e}")

    await bot.tree.sync()
    print(f"Bot listo como {bot.user} | Comandos sincronizados")

    # Registrar el callback para que el timer pueda reconstruir la caché
    news_cog = bot.get_cog("News")
    if news_cog is not None:
        def rebuild():
            news_cog.load_raw()
            news_cog.build_cache()

        set_rebuild_callback(rebuild)
        print("✅ Callback de rebuild_cache conectado al cog News.")
    else:
        print("⚠️ No se encontró el cog News. El timer no podrá reconstruir la caché automáticamente.")


if __name__ == "__main__":
    # 1. Primero arrancamos TODO lo de /timer/
    start_all_timers()

    # 2. Luego iniciamos el bot de Discord
    print("🤖 Iniciando bot de Discord...")
    bot.run(os.getenv("DISCORDTOKEN"))