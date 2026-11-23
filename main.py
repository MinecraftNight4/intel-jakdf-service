import os
import sys
import asyncio
import discord
from dotenv import load_dotenv
from discord.ext import commands

from sys_timer.scheduler import (
    start_all_timers,
    register_refresher,
    set_feed_callback, run_full_cycle)
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
    "cogs.squad",
    "cogs.follow",
    "cogs.profile",
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
        # Se importa ya (no recién en el primer ciclo): si algún módulo de feeds
        # está roto, el error se ve al arrancar y no como "Waiting..." eterno.
        try:
            from sys_timer.feed.__base import progress_tasks, run_all_feeds
        except Exception as e:
            log(f"  ✗ Feeds NO disponibles (import falló): {type(e).__name__}: {e}", "main", level="CRIT")
            return

        def feed_callback(progress):
            # El scheduler corre en otro hilo: los feeds se ejecutan en el loop del bot.
            future = asyncio.run_coroutine_threadsafe(run_all_feeds(self, progress), self.loop)
            future.result()

        set_feed_callback(feed_callback, progress_tasks())
        log("  ✓ Feeds callback", "main")

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
        ran = await loop.run_in_executor(None, run_full_cycle)
        if ran:
            await ctx.send("✅ Schedule terminado.")
        else:
            await ctx.send("⚠️ Ya hay un ciclo en ejecución; no inicié otro para no publicar todo dos veces.")
    except Exception as e:
        await ctx.send(f"❌ Error en schedule: `{e}`")
        log(f"runschedule error: {e}", "main", level="CRIT")


# ============================================================
# ARRANQUE
# ============================================================
if __name__ == "__main__":
    log("Iniciando bot...", "main")
    bot.run(os.getenv("DISCORDTOKEN"))
