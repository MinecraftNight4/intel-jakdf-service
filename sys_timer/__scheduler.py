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
    log(f"TIMER: Feature of 'cogs.news' as 'rebuild_cache' was registered.", "cache")


def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    log(f"TIMER: Feature of 'cogs.feeds' as 'feed_cache' was registered.", "cache")


def _should_run_now() -> bool:
    return datetime.now().minute in (0, 30)


def _news_loop():
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            
            #
            # SCHEDULE OF ACTIVITY...
            #
            log(f"", "main")
            log(f"================", "main")
            log(f"A NEW SCHEDULE IS AVAILABLE!", "main")
            log(f"- PART 1 | GAME NEWS:", "main")
            
            
            log(f"STATUS: REQUEST", "main")
            try:
                success = run_news_scan()
                log(f"STATUS: REQUEST | SUCCESS", "main")
            except:
                log(f"STATUS: REQUEST | FAILURE", "main", level="CRIT")
            if success is not None:    
                #
                # EMBED FOR PAGE READER
                #
                log(f"STATUS: EMBEDDING READER", "main")
                try:
                    _rebuild_cache_callback()
                    log(f"STATUS: EMBEDDING READER | SUCCESS", "main")
                except:
                    log(f"STATUS: EMBEDDING READER | FAILURE", "main", level="CRIT")
                
                #
                # EMBED FOR FEED SYSTEM
                #
                log(f"STATUS: EMBEDDING FEED", "main")
                try:
                    _feed_callback()
                except:
                    log(f"STATUS: EMBEDDING FEED | FAILURE", "main", level="CRIT")
            log(f"================", "main")

        time.sleep(20)


def start_all_timers():
    log(f"TIMER: LOADING...", "main")
    news_thread = threading.Thread(target=_news_loop, name="NewsTimer", daemon=True)
    news_thread.start()
    log(f"TIMER: Timers loaded!", "main")
