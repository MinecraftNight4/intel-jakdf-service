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
    log(f"SECTION: [GLOBAL COMMANDS] 🔁", "main", show=False)
    for ext in extensions:
        try:
            await bot.load_extension(ext)
            log(f"- COG: {ext} - SUCCESS!", "bots", show=False)
        except Exception as e:
            log(f"- COG: {ext} - FAILURE", "bots", level="CRIT", show=False)
            log(f"- COG: {ext} - FAILURE | {e}", "bots", level="CRIT", show=False)
    await bot.tree.sync()
    log(f"SECTION: [GLOBAL COMMANDS] 🚧", "main")
    
    #   LOAD PRIVATE COMMANDS        
    log(f"SECTION: [PRIVATE COMMANDS] 🔁", "main", show=False)
    try:
        from cogs.feeds import load_feeds
        data = load_feeds()
        for guild_id in data.get("allow_feed_commands", []):
            log(f"- GUILD {guild_id} LISTED!", "bots", show=False)
            try:
                await bot.tree.sync(guild=discord.Object(id=int(guild_id)))
                log(f"[✅] /feed", "bots", show=False)
                
            except Exception as e:
                log(f"[❌] /feed | Error: {e} ", "bots", level="CRIT", show=False)
    except Exception as e:
        log(f"SECTION: [PRIVATE COMMANDS] - {e}", "bots", level="CRIT", show=False)
    log(f"SECTION: [PRIVATE COMMANDS] 🚧", "main")
    
    
    #=======================================
    #   LOADING TIMER INSTANCE...
    #=======================================
    log(f"TIMER : [RAW NEWS] 🔁", "main", show=False)
    news_cog = bot.get_cog("News")
    if news_cog is not None:
        def rebuild():
            news_cog.load_raw()
            news_cog.build_cache()
        
        set_rebuild_callback(rebuild)
        log(f"RAW NEWS: A temp build was made from scratch!", "main", show=False)
    else:
        log(f"RAW NEWS: The embed was not possible to be build.", "main", level="CRIT", show=False)
    log(f"TIMER: [BOOT NEWS] 🚧", "main")

    log(f"TIMER : [BOOT FEED] 🔁", "main", show=False)
    def feed_callback():
        asyncio.run_coroutine_threadsafe(process_feed_game_all(bot), bot.loop)
    set_feed_callback(feed_callback)
    log(f"TIMER: [BOOT FEED] 🚧", "main")
    log(f"🚧BOOT THREAD CLOSED🚧", "main")
    


if __name__ == "__main__":
    log(f"", "main")
    
    log(f"SYSTEM BOOTING...", "main", show=False)
    log(f"BOOT: Loading Timers...", "main")
    start_all_timers()

    log(f"BOOT: Loading Bot...", "main")
    bot.run(os.getenv("DISCORDTOKEN"))