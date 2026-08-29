import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import start_all_timers, set_rebuild_callback, set_feed_callback
from sys_timer.feed.feed_game_general import process_feed_game_general
from sys_timer.feed.feed_game_service import process_feed_game_service
from sys_timer.feed.feed_game_event import process_feed_game_event
from sys_timer.feed.feed_game_gacha import process_feed_game_gacha
from sys_timer.feed.feed_xcom import process_feed_xcom
from logger import info, warn, crit, log

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

#@bot.command(name="runschedule")
#@commands.is_owner()
#async def run_schedule(ctx):
#    """Fuerza la ejecución completa del scheduler (news + xcom + feeds)."""
#    await ctx.send("⏳ Ejecutando schedules...")
#
#    # 1. Scrape de noticias
#    #try:
#    #    from sys_timer.news_schedule import run_news_scan
#    #    success = run_news_scan()
#    #    await ctx.send(f"✅ News scan: `{'OK' if success else 'FAIL'}`")
#    #except Exception as e:
#    #    await ctx.send(f"❌ News scan error: `{e}`")
#
#    # 2. Scrape de XCom
#    #try:
#    #    from sys_timer.xcom_schedule import run_xcom_scan
#    #    xcom_success = run_xcom_scan()
#    #    await ctx.send(f"✅ XCom scan: `{'OK' if xcom_success else 'FAIL'}`")
#    #except Exception as e:
#    #    await ctx.send(f"❌ XCom scan error: `{e}`")
#
#    # 3. Rebuild cache de news
#    try:
#        news_cog = bot.get_cog("News")
#        if news_cog is not None:
#            news_cog.load_raw()
#            news_cog.build_cache()
#            await ctx.send("✅ Cache rebuild: `OK`")
#        else:
#            await ctx.send("⚠️ Cog News no encontrado")
#    except Exception as e:
#        await ctx.send(f"❌ Cache rebuild error: `{e}`")
#
#    # 4. Publicar todos los feeds
#    try:
#        #from sys_timer.feed.feed_game_all import process_feed_game_all
#        #from sys_timer.feed.feed_game_gacha import process_feed_game_gacha
#        #from sys_timer.feed.feed_game_event import process_feed_game_event
#        #from sys_timer.feed.feed_game_service import process_feed_game_update
#        from sys_timer.feed.feed_xcom import process_feed_xcom
#
#        #await process_feed_game_all(bot)
#        #await process_feed_game_gacha(bot)
#        #await process_feed_game_event(bot)
#        #await process_feed_game_update(bot)
#        await process_feed_xcom(bot)
#
#        await ctx.send("✅ Feeds publicados")
#    except Exception as e:
#        await ctx.send(f"❌ Feeds error: `{e}`")
#
#    await ctx.send("🏁 Schedule completo terminado.")



@bot.event
async def on_ready():
    #=======================================
    #   COG DEPLOYMENT...
    #=======================================
    log(f"BOTS: [COGS] LOADING...", "main")
    extensions = [
        "cogs.news",
        "cogs.feeds",
        "cogs.follow",
    ]
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            log(f"- [COG: {ext}]: SUCCESS", "bots", show=False)
        except Exception as e:
            log(f"- [COG: {ext}]: FAILURE - {e}", "bots", LEVEL="CRIT", show=False)
    
    try:
        await bot.tree.sync()
        log(f"[BOT WAKE-UP]: [GLOBAL COMMAND] SUCCESS", "bots", show=False)
    except Exception as e:
        log(f"[BOT WAKE-UP]: [GLOBAL COMMAND] FAILURE - {e}", "bots", level="CRIT", show=False)
    log(f"BOTS: [COGS] DEPLOYED!", "main")
    
    
    #   LOAD PRIVATE COMMANDS        
    log(f"BOTS: [PRIV] LOADING...", "main")
    try:
        from cogs.feeds import load_feeds
        data = load_feeds()
        
        for guild_id in data.get("allow_feed_commands", []):    
            try:
                await bot.tree.sync(guild=discord.Object(id=int(guild_id)))
                log(f"- [{guild_id}]: SUCCESS", "bots", show=False)
            except Exception as e:
                log(f"- [{guild_id}]: FAILURE - {e}", "bots", level="CRIT", show=False)
    except Exception as e:
        log(f"BOTS: [PRIV] FAILURE - {e}", "bots", level="CRIT", show=False)
    log(f"BOTS: [PRIV] DEPLOYED!", "main")
    
    
    #=======================================
    #   LOADING TIMER INSTANCE...
    #=======================================
    log(f"BOTS: [TIME] LOADING...", "main")


    log(f"[TIMER DEPLOY]: NEWS - LOADING...", "cache", show=False)
    news_cog = bot.get_cog("News")
    if news_cog is not None:
        def rebuild():
            news_cog.load_raw()
            news_cog.build_cache()
        set_rebuild_callback(rebuild)
    log(f"[TIMER DEPLOY]: NEWS - DEPLOYED!", "cache", show=False)


    log(f"[TIMER DEPLOY]: FEED - LOADING...", "cache", show=False)
    async def process_all_feeds():
        tasks = [
            process_feed_game_general(bot),
            process_feed_game_service(bot),
            process_feed_game_gacha(bot),
            process_feed_game_event(bot),
            process_feed_xcom(bot),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
    
    
    def feed_callback():
        asyncio.run_coroutine_threadsafe(process_all_feeds(), bot.loop)


    set_feed_callback(feed_callback)
    log(f"[TIMER DEPLOY]: FEED - DEPLOYED!", "cache", show=False)
    log(f"BOTS: [TIME] DEPLOYED!", "main")
    


if __name__ == "__main__":
    log(f"", "main")
    start_all_timers()
    bot.run(os.getenv("DISCORDTOKEN"))