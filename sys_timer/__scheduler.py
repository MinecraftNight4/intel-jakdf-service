import threading
import time
from datetime import datetime
from .news_schedule import run_news_scan
from .xcom_schedule import run_xcom_scan
from web_get.request_rmap import run_rmap_scan
from logger import info, warn, crit, log

# Callbacks que el bot registrará
_rebuild_cache_callback = None
_feed_callback = None


def set_rebuild_callback(callback):
    global _rebuild_cache_callback
    _rebuild_cache_callback = callback
    log(f"TIMER: [REGISTER: cogs.news]", "timer", show=False)

def set_rebuild_calendar_callback(callback):
    global _calendar_cache_callback
    _calendar_cache_callback = callback
    log(f"TIMER: [REGISTER: cogs.calendar]", "timer", show=False)

def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    log(f"TIMER: [REGISTER: cogs.feeds]", "timer", show=False)


def _should_run_now() -> bool:
    return datetime.now().minute in (0, 30)


def _news_loop():
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            
            log(f"", "timer")
            log(f"========[⬇️SCHEDULER⬇️]========", "timer")
            
            # 1. Scrape de noticias del juego
            try:
                success = run_news_scan()
                log(f"STATUS: REQUEST NEWS [SUCCESS]", "timer")
            except:
                log(f"STATUS: REQUEST NEWS [FAILURE]", "timer", level="CRIT")
                success = False

            # 2. Scrape de XCom (tweets)
            try:
                xcom_success = run_xcom_scan()
                log(f"STATUS: REQUEST XCOM [SUCCESS]", "timer")
            except:
                log(f"STATUS: REQUEST XCOM [FAILURE]", "timer", level="CRIT")
                xcom_success = False

            # 3. Procesar roadmaps con Gemini
            try:
                rmap_success = run_rmap_scan()
                log(f"STATUS: REQUEST RMAP [SUCCESS]", "timer")
            except:
                log(f"STATUS: REQUEST RMAP [FAILURE]", "timer", level="CRIT")
                rmap_success = False

            if success is not None or xcom_success:
                
                # 4. Rebuild cache de news
                try:
                    if _rebuild_cache_callback:
                        _rebuild_cache_callback()
                    log(f"STATUS: EMBED READER [SUCCESS]", "timer")
                except:
                    log(f"STATUS: EMBED READER [FAILURE]", "timer", level="CRIT")
                
                # 5. Publicar feeds (news + xcom)
                try:
                    if _feed_callback:
                        _feed_callback()
                    log(f"STATUS: CROSSPOST [SUCCESS]", "timer")
                except:
                    log(f"STATUS: CROSSPOST [FAILURE]", "timer", level="CRIT")

            log(f"========[⬆️SCHEDULER⬆️]========", "timer")
        time.sleep(20)


def start_all_timers():
    log(f"TIMER: LOADING...", "bots", show=False)
    news_thread = threading.Thread(target=_news_loop, name="NewsTimer", daemon=True)
    news_thread.start()
    log(f"TIMER: Timers loaded!", "bots", show=False)