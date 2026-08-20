import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import start_all_timers, set_rebuild_callback, set_feed_callback
from sys_timer.feed.feed_game_all import process_feed_game_all

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
        "cogs.feeds",
    ]

    for ext in extensions:
        try:
            await bot.load_extension(ext)
            print(f"✅ Cargado: {ext}")
        except Exception as e:
            print(f"❌ Error al cargar {ext}: {e}")

    # Sync global
    await bot.tree.sync()
    print("✅ Comandos globales sincronizados")

    # Sync de las guilds que tienen /feed
    try:
        from cogs.feeds import load_feeds
        data = load_feeds()
        for guild_id in data.get("allow_feed_commands", []):
            try:
                await bot.tree.sync(guild=discord.Object(id=int(guild_id)))
                print(f"✅ Sincronizado en guild {guild_id}")
            except Exception as e:
                print(f"❌ Error sync guild {guild_id}: {e}")
    except Exception as e:
        print(f"⚠️ Error al sincronizar feeds: {e}")

    print(f"Bot listo como {bot.user}")

    # ============================================================
    # Callbacks del timer
    # ============================================================
    news_cog = bot.get_cog("News")
    if news_cog is not None:
        def rebuild():
            news_cog.load_raw()
            news_cog.build_cache()

        set_rebuild_callback(rebuild)
        print("✅ Callback de rebuild_cache conectado")
    else:
        print("⚠️ No se encontró el cog News")

    # Callback de feeds (se ejecuta en el loop del bot)
    def feed_callback():
        asyncio.run_coroutine_threadsafe(process_feed_game_all(bot), bot.loop)

    set_feed_callback(feed_callback)
    print("✅ Callback de feeds conectado")


if __name__ == "__main__":
    # 1. Primero arrancamos TODO lo de /timer/
    start_all_timers()

    # 2. Luego iniciamos el bot de Discord
    print("🤖 Iniciando bot de Discord...")
    bot.run(os.getenv("DISCORDTOKEN"))