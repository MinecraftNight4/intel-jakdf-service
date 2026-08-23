import threading
import time
from datetime import datetime
from .news_schedule import run_news_scan
from logger import info, warn, crit, log

# Callbacks que el bot registrará
_rebuild_cache_callback = None
_feed_callback = None


def set_rebuild_callback(callback):
    global _rebuild_cache_callback
    _rebuild_cache_callback = callback
    log(f"TIMER: [REGISTER: cogs.news]", "timer", show=False)


def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    log(f"TIMER: [REGISTER: cogs.feeds]", "timer", show=False)


def _should_run_now() -> bool:
    return datetime.now().minute in (0, 15, 30)


def _news_loop():
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        if current_minute in (0, 15, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            
            #
            # SCHEDULE OF ACTIVITY...
            #
            log(f"", "timer")
            log(f"========[⬇️SCHEDULER⬇️]========", "timer")
            
            try:
                success = run_news_scan()
                log(f"STATUS: REQUEST [SUCCESS]", "timer")
            except:
                log(f"STATUS: REQUEST [FAILURE]", "timer", level="CRIT")
            if success is not None:
                
                #
                # EMBED FOR PAGE READER
                #
                try:
                    _rebuild_cache_callback()
                    log(f"STATUS: EMBED READER [SUCCESS]", "timer")
                except:
                    log(f"STATUS: EMBED READER [FAILURE]", "timer", level="CRIT")
                
                #
                # EMBED FOR FEED SYSTEM
                #
                try:
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
