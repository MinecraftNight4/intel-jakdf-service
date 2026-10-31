import threading
import time
from datetime import datetime

from .news_schedule import run_news_scan
from .xcom_schedule import run_xcom_scan
from web_get.request_rmap import run_rmap_scan
from logger import log
from .progress import ProgressDisplay

# ============================================================
# Callbacks (se registran desde main.py)
# ============================================================
_calendar_cache_callback = None
_rebuild_cache_callback = None
_feed_callback = None


def set_rebuild_callback(callback):
    global _rebuild_cache_callback
    _rebuild_cache_callback = callback
    log("TIMER: [REGISTER: cogs.news]", "timer", show=False)


def set_rebuild_calendar_callback(callback):
    global _calendar_cache_callback
    _calendar_cache_callback = callback
    log("TIMER: [REGISTER: cogs.calendar]", "timer", show=False)


def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    log("TIMER: [REGISTER: cogs.feeds]", "timer", show=False)


# ============================================================
# Loop principal del timer
# ============================================================
def _news_loop():
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            run_full_cycle()

        time.sleep(20)


# ============================================================
# Ciclo completo del scheduler
# ============================================================
def run_full_cycle():
    progress = ProgressDisplay()
    progress.start()

    # --------------------------------------------------------
    # PHASE 1 – Fetching
    # --------------------------------------------------------
    progress.set_phase(1)
    progress.add_task("news", "Fetching Game News", eta_seconds=40)
    progress.add_task("xcom", "Fetching VX API", eta_seconds=20)

    # News
    progress.start_task("news")
    news_ok = False
    try:
        news_ok = bool(run_news_scan())
        progress.success("news") if news_ok else progress.failure("news")
    except Exception:
        progress.failure("news")
        news_ok = False

    # XCom
    progress.start_task("xcom")
    xcom_ok = False
    try:
        xcom_ok = bool(run_xcom_scan(progress=progress, progress_key="xcom"))
        progress.success("xcom") if xcom_ok else progress.failure("xcom")
    except Exception:
        progress.failure("xcom")
        xcom_ok = False

    # Si Phase 1 falló completamente → abortar
    if not (news_ok or xcom_ok):
        progress.stop()
        log("========[SCHEDULER ABORTED - Phase 1 failed]========", "timer")
        return

    # --------------------------------------------------------
    # PHASE 2 – Building
    # --------------------------------------------------------
    progress.set_phase(2)
    progress.add_task("embed", "Building News Embed", eta_seconds=10)
    progress.add_task("calendar", "Building Calendar", eta_seconds=15)
    progress.add_task("feeds_build", "Building Feeds", eta_seconds=5)

    # News Embed / Cache
    progress.start_task("embed")
    try:
        if _rebuild_cache_callback:
            _rebuild_cache_callback()
        progress.success("embed")
    except Exception:
        progress.failure("embed")

    # Calendar
    progress.start_task("calendar")
    try:
        if _calendar_cache_callback:
            _calendar_cache_callback()
        progress.success("calendar")
    except Exception:
        progress.failure("calendar")

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
    thread = threading.Thread(target=_news_loop, name="NewsTimer", daemon=True)
    thread.start()
    log("TIMER: Timers loaded!", "bots", show=False)