import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import start_all_timers, set_rebuild_callback, set_feed_callback
from sys_timer.feed.feed_game_all import process_feed_game_all
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


@bot.event
async def on_ready():
    
    #=======================================
    #   LOADING BOT INSTANCE...
    #=======================================
    extensions = [
        "cogs.news",
        "cogs.feeds",
    ]

    # LOAD GLOBAL COMMAND & LISTENERS
    for ext in extensions:
        log(f"GLOBAL COMMANDS: Loading...", "main")
        try:
            await bot.load_extension(ext)
            log(f"COG: {ext} - SUCCESS", "bots")
        except Exception as e:
            log(f"COG: {ext} - FAILURE", "bots", level="CRIT")
            log(f"COG: {ext} - FAILURE | {e}", "bots", level="CRIT", show=False)
        log(f"GLOBAL COMMANDS: Closed!", "main")
    await bot.tree.sync()
    
    #   LOAD PRIVATE COMMANDS        
    try:
        log(f"PRIVATE COMMANDS: Loading...", "main")
        from cogs.feeds import load_feeds
        data = load_feeds()
        for guild_id in data.get("allow_feed_commands", []):
            try:
                await bot.tree.sync(guild=discord.Object(id=int(guild_id)))
                log(f"/FEEDS | {guild_id} updated", "bots", show=False)
            except Exception as e:
                log(f"/FEEDS | {guild_id} failure: {e}", "bots", level="CRIT", show=False)
    except Exception as e:
        log(f"/FEEDS exception! {e}", "bots", level="CRIT", show=False)
    
    #   BOT LOADING 
    log(f"SERVICE: Closed!", "bots", level="CRIT", show=False)
    log(f"BOT OPERATIONS: READY!", "main")
    
    
    #=======================================
    #   LOADING TIMER INSTANCE...
    #=======================================
    log(f"TIMER: Loading...", "bots")
    
    news_cog = bot.get_cog("News")
    if news_cog is not None:
        def rebuild():
            news_cog.load_raw()
            news_cog.build_cache()
        
        set_rebuild_callback(rebuild)
        log(f"[rebuild_cache] instance loaded.", "bots", show=False)
    else:
        log(f"[rebuild_cache] was not found!", "bots", level="CRIT", show=False)
    
    log(f"TIMER: Saving Feed Task...", "bots", show=False)
    def feed_callback():
        asyncio.run_coroutine_threadsafe(process_feed_game_all(bot), bot.loop)
    
    set_feed_callback(feed_callback)
    log(f"TIMER: READY!", "bots", show=False)
    log(f"TIMER OPERATIONS: READY!", "main")


if __name__ == "__main__":
    log(f"~", "main")
    
    log(f"SYSTEM BOOTING...", "main")
    log(f"BOOT: Loading Timers...", "main")
    start_all_timers()

    log(f"BOOT: Loading Bot", "main")
    bot.run(os.getenv("DISCORDTOKEN"))