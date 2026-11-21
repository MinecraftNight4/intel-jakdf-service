"""
Orquestador de todos los feeds. El scheduler lo llama (vía main.py) en la
fase 3 de cada ciclo.

Orden y claves de progreso: deben coincidir con `feed_tasks` de
sys_timer/scheduler.py.
"""
from logger import log

from .feed_news import NEWS_FEEDS, process_news_feed
from .feed_game_store import process_feed_game_store
from .feed_xcom import process_feed_xcom

XCOM_PROGRESS_KEYS = [
    "xcom-kj8_thegame_en",
    "xcom-kaijuno8_o_en",
    "xcom-kj8_thegame",
    "xcom-kaijuno8_o",
]


async def run_all_feeds(bot, progress) -> None:
    # Noticias del juego (general, service, gacha, event) + tienda, con progreso dinámico
    jobs = [(key, spec) for key, spec in NEWS_FEEDS.items()]
    jobs.append(("store", None))

    for key, spec in jobs:
        progress.start_task(key)
        try:
            if spec is None:
                await process_feed_game_store(bot, progress=progress, progress_key=key)
            else:
                await process_news_feed(bot, spec, progress=progress, progress_key=key)
            progress.success(key)
        except Exception as e:
            progress.failure(key)
            log(f"Feed {key} error: {e}", "feed", level="CRIT", show=False)

    # x.com: maneja el progreso de cada cuenta por su cuenta
    try:
        await process_feed_xcom(bot, progress=progress)
    except Exception as e:
        for key in XCOM_PROGRESS_KEYS:
            progress.failure(key)
        log(f"Feed XCom error: {e}", "feed", level="CRIT", show=False)
