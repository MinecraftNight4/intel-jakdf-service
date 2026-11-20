import threading
import time
from datetime import datetime
from typing import Callable, Dict, NamedTuple

from .news_schedule import run_news_scan
from .xcom_schedule import run_xcom_scan
from .sale_schedule import run_sale_scan_wrapper
from web_get.request_rmap import run_rmap_scan
from logger import log
from .progress import ProgressDisplay


# ============================================================
# Registro de refreshers (se registran desde main.py)
#
# Cada cog que expone `refresh_cache()` se registra solo, así que
# un cog nuevo no puede quedar fuera del ciclo por olvido.
# La `key` debe existir en ProgressDisplay (fase 2).
# ============================================================
class _Refresher(NamedTuple):
    key: str
    label: str
    eta: int
    func: Callable[[], None]


_refreshers: Dict[str, _Refresher] = {}
_feed_callback = None


def register_refresher(name: str, func: Callable[[], None], key: str, label: str, eta: int = 10):
    """Registra (o reemplaza) la función que reconstruye la caché de un cog."""
    _refreshers[name] = _Refresher(key=key, label=label, eta=eta, func=func)
    log(f"TIMER: [REGISTER: {name}]", "timer", show=False)


def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    log("TIMER: [REGISTER: cogs.feeds]", "timer", show=False)


# ============================================================
# Loop principal del timer
# ============================================================
def _timer_loop():
    last_run_minute = -1

    while True:
        current_minute = datetime.now().minute

        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            try:
                run_full_cycle()
            except Exception as e:
                # Que un error inesperado no mate el hilo del timer.
                log(f"SCHEDULER CRASH: {e}", "timer", level="CRIT")

        time.sleep(20)


# ============================================================
# Ciclo completo del scheduler
# ============================================================
def _run_fetch(progress: ProgressDisplay, key: str, func: Callable[[], bool]) -> bool:
    progress.start_task(key)
    try:
        ok = bool(func())
    except Exception as e:
        log(f"FETCH ERROR [{key}]: {e}", "timer", level="CRIT", show=False)
        ok = False
    progress.success(key) if ok else progress.failure(key)
    return ok


def run_full_cycle():
    progress = ProgressDisplay()
    progress.start()

    # --------------------------------------------------------
    # PHASE 1 – Fetching
    # --------------------------------------------------------
    progress.set_phase(1)

    progress.add_task("news", "Fetching NEWS", eta_seconds=60)
    progress.add_task("xcom", "Fetching xAPI", eta_seconds=20)
    progress.add_task("rmap", "Fetching RMAP", eta_seconds=60)
    progress.add_task("sale", "Fetching SALE", eta_seconds=40)

    sale_ok = _run_fetch(progress, "sale", run_sale_scan_wrapper)
    news_ok = _run_fetch(progress, "news", run_news_scan)
    xcom_ok = _run_fetch(progress, "xcom", lambda: run_xcom_scan(progress=progress, progress_key="xcom"))
    _run_fetch(progress, "rmap", run_rmap_scan)

    # Si Phase 1 falló completamente → abortar (rmap no cuenta)
    if not (news_ok or xcom_ok or sale_ok):
        progress.stop()
        log("========[SCHEDULER ABORTED - Phase 1 failed]========", "timer")
        return

    # --------------------------------------------------------
    # PHASE 2 – Building
    # --------------------------------------------------------
    progress.set_phase(2)

    refreshers = list(_refreshers.values())
    for r in refreshers:
        progress.add_task(r.key, r.label, eta_seconds=r.eta)
    progress.add_task("feeds_build", "Building Feeds", eta_seconds=5)

    for r in refreshers:
        progress.start_task(r.key)
        try:
            r.func()
            progress.success(r.key)
        except Exception as e:
            progress.failure(r.key)
            log(f"REBUILD ERROR [{r.key}]: {e}", "timer", level="CRIT", show=False)

    # Feeds build (marcado como listo)
    progress.start_task("feeds_build")
    progress.success("feeds_build")

    # --------------------------------------------------------
    # PHASE 3 – Posting
    # --------------------------------------------------------
    progress.set_phase(3)

    feed_tasks = [
        ("general",                 "Posting `game_general`",            50),
        ("service",                 "Posting `game_service`",            50),
        ("gacha",                   "Posting `game_gacha`",              35),
        ("event",                   "Posting `game_event`",              35),
        ("store",                   "Posting `game_store`",              40),
        ("xcom-kj8_thegame_en",     "Posting `X - @kj8_thegame_en`",     25),
        ("xcom-kaijuno8_o_en",      "Posting `X - @kaijuno8_o_en`",      25),
        ("xcom-kj8_thegame",        "Posting `X - @kj8_thegame`",        25),
        ("xcom-kaijuno8_o",         "Posting `X - @kaijuno8_o`",         25),
    ]

    for key, label, eta in feed_tasks:
        progress.add_task(key, label, eta_seconds=eta)

    # Ejecutar el posting (espera real)
    if _feed_callback:
        try:
            _feed_callback(progress)
        except Exception as e:
            log(f"FEED CALLBACK ERROR: {e}", "timer", level="CRIT")

    progress.stop()
    log("========[SCHEDULER COMPLETE]========", "timer")


# ============================================================
# Arranque
# ============================================================
def start_all_timers():
    log("TIMER: LOADING...", "bots", show=False)
    thread = threading.Thread(target=_timer_loop, name="SchedulerTimer", daemon=True)
    thread.start()
    log("TIMER: Timers loaded!", "bots", show=False)
