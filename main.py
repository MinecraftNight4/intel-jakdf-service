import os
import sys
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.scheduler import (
    start_all_timers,
    register_refresher,
    set_feed_callback,
    run_full_cycle,
)
from logger import log

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
OWNER_ID = 219152885458534401

EXTENSIONS = [
    "cogs.news",
    "cogs.sale",
    "cogs.feeds",
    "cogs.follow",
    "cogs.calendar",
]


# ============================================================
# BOT
# ============================================================
class KaijuBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.all())
        self._timers_started = False

    # --------------------------------------------------------
    # setup_hook: corre UNA sola vez, antes de conectar al gateway.
    # (on_ready puede dispararse de nuevo en cada reconexión.)
    # --------------------------------------------------------
    async def setup_hook(self):
        await self._load_extensions()
        await self._sync_commands()
        self._register_refreshers()
        self._register_feed_callback()

    async def _load_extensions(self):
        log("Cargando cogs...", "main")
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log(f"  ✓ {ext}", "main")
            except Exception as e:
                log(f"  ✗ {ext} → {e}", "main", level="CRIT")

    async def _sync_commands(self):
        # Sync global
        try:
            await self.tree.sync()
            log("Slash commands (global) sincronizados", "main")
        except Exception as e:
            log(f"Error sync global: {e}", "main", level="CRIT")

        # Sync privado (feeds)
        try:
            from cogs.feeds import load_feeds
            data = load_feeds()
            for guild_id in data.get("allow_feed_commands", []):
                try:
                    await self.tree.sync(guild=discord.Object(id=int(guild_id)))
                    log(f"  ✓ Sync guild {guild_id}", "main")
                except Exception as e:
                    log(f"  ✗ Sync guild {guild_id}: {e}", "main", level="CRIT")
        except Exception as e:
            log(f"Error cargando allow_feed_commands: {e}", "main", level="CRIT")

        log("Cogs desplegados", "main")

    # --------------------------------------------------------
    # Scheduler: todo cog con `refresh_cache()` se registra solo.
    # Atributos opcionales del cog: REFRESH_KEY, REFRESH_LABEL, REFRESH_ETA
    # --------------------------------------------------------
    def _register_refreshers(self):
        log("Registrando timers...", "main")
        for name, cog in self.cogs.items():
            func = getattr(cog, "refresh_cache", None)
            if not callable(func):
                continue
            register_refresher(
                name,
                func,
                key=getattr(cog, "REFRESH_KEY", f"embed_{name.lower()}"),
                label=getattr(cog, "REFRESH_LABEL", f"Building {name}"),
                eta=getattr(cog, "REFRESH_ETA", 10),
            )
            log(f"  ✓ {name} cache callback", "main")

    def _register_feed_callback(self):
        def feed_callback(progress):
            future = asyncio.run_coroutine_threadsafe(self._process_all_feeds(progress), self.loop)
            future.result()

        set_feed_callback(feed_callback)
        log("  ✓ Feeds callback", "main")

    async def _process_all_feeds(self, progress):
        from sys_timer.feed.feed_game_general import process_feed_game_general
        from sys_timer.feed.feed_game_service import process_feed_game_service
        from sys_timer.feed.feed_game_gacha import process_feed_game_gacha
        from sys_timer.feed.feed_game_event import process_feed_game_event
        from sys_timer.feed.feed_game_store import process_feed_game_store
        from sys_timer.feed.feed_xcom import process_feed_xcom

        # Game feeds con progreso dinámico
        mapping = [
            ("general", process_feed_game_general),
            ("service", process_feed_game_service),
            ("gacha",   process_feed_game_gacha),
            ("event",   process_feed_game_event),
            ("store",   process_feed_game_store),
        ]

        for key, func in mapping:
            progress.start_task(key)
            try:
                await func(self, progress=progress, progress_key=key)
                progress.success(key)
            except Exception as e:
                progress.failure(key)
                log(f"Feed {key} error: {e}", "feed", level="CRIT", show=False)

        # XCom (todavía sin progreso dinámico por ahora)
        try:
            await process_feed_xcom(self, progress=progress)
        except Exception as e:
            for key in ["xcom-kj8_thegame_en", "xcom-kaijuno8_o_en", "xcom-kj8_thegame", "xcom-kaijuno8_o"]:
                progress.failure(key)
            log(f"Feed XCom error: {e}", "feed", level="CRIT", show=False)

    # --------------------------------------------------------
    # on_ready: solo logs + arranque (único) del timer.
    # El timer arranca acá y no antes, para que un ciclo no caiga
    # sobre un bot que todavía no está conectado.
    # --------------------------------------------------------
    async def on_ready(self):
        log("", "main")
        log(f"BOT ONLINE | {self.user} (ID: {self.user.id})", "main")
        log("=" * 50, "main")

        if not self._timers_started:
            self._timers_started = True
            start_all_timers()
            log("Timers listos", "main")

        log("=" * 50, "main")
        log(f"Bot listo | Latencia: {round(self.latency * 1000)}ms", "main")


bot = KaijuBot()


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
        # Ejecutamos en un hilo para no bloquear el bot
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, run_full_cycle)
        await ctx.send("✅ Schedule terminado.")
    except Exception as e:
        await ctx.send(f"❌ Error en schedule: `{e}`")
        log(f"runschedule error: {e}", "main", level="CRIT")


# ============================================================
# ARRANQUE
# ============================================================
if __name__ == "__main__":
    log("Iniciando bot...", "main")
    bot.run(os.getenv("DISCORDTOKEN"))
