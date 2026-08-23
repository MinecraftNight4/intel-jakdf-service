import os
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.__scheduler import start_all_timers, set_rebuild_callback, set_feed_callback
from sys_timer.feed.feed_game_gacha import process_feed_game_gacha
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
    #   COG DEPLOYMENT...
    #=======================================
    log(f"BOTS: [COGS] LOADING...", "main")
    extensions = [
        "cogs.news",
        "cogs.feeds",
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
    def feed_callback():
        asyncio.run_coroutine_threadsafe(process_feed_game_all(bot), bot.loop)
        asyncio.run_coroutine_threadsafe(process_feed_game_gacha(bot), bot.loop)
    set_feed_callback(feed_callback)
    log(f"[TIMER DEPLOY]: FEED - DEPLOYED!", "cache", show=False)
    log(f"BOTS: [TIME] DEPLOYED!", "main")
    


if __name__ == "__main__":
    log(f"", "main")
    start_all_timers()
    bot.run(os.getenv("DISCORDTOKEN"))