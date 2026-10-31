import os
import sys
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import (
    start_all_timers,
    set_rebuild_callback,
    set_rebuild_calendar_callback,
    set_feed_callback
)
from logger import log

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
OWNER_ID = 219152885458534401
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


# ============================================================
# COMANDOS DE ADMINISTRACIÓN
# ============================================================
@bot.command(name="redeploy")
@commands.is_owner()
async def redeploy(ctx: commands.Context):
    """Reinicia completamente el bot sin cerrar la consola."""
    if ctx.author.id != OWNER_ID:
        return

    await ctx.send("♻️ **Redeploying...** El bot se reiniciará en unos segundos.")
    log("BOT: Redeploy solicitado por el owner", "main")

    await bot.close()

    # Reinicia el proceso actual
    os.execv(sys.executable, [sys.executable] + sys.argv)


@bot.command(name="runschedule")
@commands.is_owner()
async def run_schedule(ctx: commands.Context):
    """Fuerza la ejecución completa del scheduler."""
    if ctx.author.id != OWNER_ID:
        return

    await ctx.send("⏳ Ejecutando schedule completo...")
    try:
        from sys_timer.__scheduler import run_full_cycle
        # Ejecutamos en un hilo para no bloquear el bot
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_full_cycle)
        await ctx.send("✅ Schedule terminado.")
    except Exception as e:
        await ctx.send(f"❌ Error en schedule: `{e}`")
        log(f"runschedule error: {e}", "main", level="CRIT")


# ============================================================
# EVENTO on_ready
# ============================================================
@bot.event
async def on_ready():
    log("", "main")
    log(f"BOT ONLINE | {bot.user} (ID: {bot.user.id})", "main")
    log("=" * 50, "main")

    # --------------------------------------------------------
    # 1. Cargar Cogs
    # --------------------------------------------------------
    log("Cargando cogs...", "main")
    extensions = [
        "cogs.news",
        "cogs.feeds",
        "cogs.follow",
        "cogs.calendar",
    ]

    for ext in extensions:
        try:
            await bot.load_extension(ext)
            log(f"  ✓ {ext}", "main")
        except Exception as e:
            log(f"  ✗ {ext} → {e}", "main", level="CRIT")

    # Sync global
    try:
        await bot.tree.sync()
        log("Slash commands (global) sincronizados", "main")
    except Exception as e:
        log(f"Error sync global: {e}", "main", level="CRIT")

    # Sync privado (feeds)
    try:
        from cogs.feeds import load_feeds
        data = load_feeds()
        for guild_id in data.get("allow_feed_commands", []):
            try:
                await bot.tree.sync(guild=discord.Object(id=int(guild_id)))
                log(f"  ✓ Sync guild {guild_id}", "main")
            except Exception as e:
                log(f"  ✗ Sync guild {guild_id}: {e}", "main", level="CRIT")
    except Exception as e:
        log(f"Error cargando allow_feed_commands: {e}", "main", level="CRIT")

    log("Cogs desplegados", "main")

    # --------------------------------------------------------
    # 2. Registrar callbacks del scheduler
    # --------------------------------------------------------
    log("Registrando timers...", "main")

    # News cache
    news_cog = bot.get_cog("News")
    if news_cog:
        def rebuild_news():
            news_cog.load_raw()
            news_cog.build_cache()
        set_rebuild_callback(rebuild_news)
        log("  ✓ News cache callback", "main")

    # Calendar cache
    calendar_cog = bot.get_cog("Calendar")
    if calendar_cog:
        def rebuild_calendar():
            calendar_cog.rebuild_calendar_cache()
        set_rebuild_calendar_callback(rebuild_calendar)
        log("  ✓ Calendar cache callback", "main")

    # Feeds (con progress)
    async def process_all_feeds(progress):
        from sys_timer.feed.feed_game_general import process_feed_game_general
        from sys_timer.feed.feed_game_service import process_feed_game_service
        from sys_timer.feed.feed_game_gacha import process_feed_game_gacha
        from sys_timer.feed.feed_game_event import process_feed_game_event
        from sys_timer.feed.feed_xcom import process_feed_xcom

        # Game feeds con progreso dinámico
        mapping = [
            ("general", process_feed_game_general),
            ("service", process_feed_game_service),
            ("gacha",   process_feed_game_gacha),
            ("event",   process_feed_game_event),
        ]

        for key, func in mapping:
            progress.start_task(key)
            try:
                await func(bot, progress=progress, progress_key=key)
                progress.success(key)
            except Exception as e:
                progress.failure(key)
                log(f"Feed {key} error: {e}", "feed", level="CRIT", show=False)

        # XCom (todavía sin progreso dinámico por ahora)
        try:
            await process_feed_xcom(bot, progress=progress)
        except Exception as e:
            for key in ["xcom-kj8_thegame_en", "xcom-kaijuno8_o_en", "xcom-kj8_thegame", "xcom-kaijuno8_o"]:
                progress.failure(key)
            log(f"Feed XCom error: {e}", "feed", level="CRIT", show=False)

    def feed_callback(progress):
        future = asyncio.run_coroutine_threadsafe(process_all_feeds(progress), bot.loop)
        future.result()

    set_feed_callback(feed_callback)
    log("  ✓ Feeds callback", "main")

    log("Timers listos", "main")
    log("=" * 50, "main")
    log(f"Bot listo | Latencia: {round(bot.latency * 1000)}ms", "main")


# ============================================================
# ARRANQUE
# ============================================================
if __name__ == "__main__":
    log("Iniciando bot...", "main")
    start_all_timers()
    bot.run(os.getenv("DISCORDTOKEN"))