"""
Orquestador de todos los feeds (fase 3 de cada ciclo del scheduler).

Aquí está la ÚNICA lista de feeds para el panel de progreso:
    progress_tasks()  → lo que el scheduler muestra en la fase 3
    run_all_feeds()   → lo que realmente se ejecuta

Para sumar un feed de noticias basta con agregarlo a NEWS_FEEDS (feed_news.py).
"""
from typing import List, Tuple

from logger import log
from web_get.request_xcom import KaijuReadXCom

from .feed_news import NEWS_FEEDS, process_news_feed
from .feed_publish import publish_latest
from .feed_store import process_feed_game_store
from .feed_xcom import process_feed_xcom

STORE_KEY = "store"
STORE_ETA = 40
XCOM_ETA = 25


def _xcom_keys() -> List[str]:
    # Misma clave que usa feed_xcom: "xcom-<cuenta en minúsculas>"
    return [f"xcom-{account.lower()}" for account in KaijuReadXCom().accounts]


def progress_tasks() -> List[Tuple[str, str, int]]:
    """[(key, label, eta)] en el orden en que se muestran en el panel."""
    tasks = [(key, f"Posting `game_{key}`", spec.eta) for key, spec in NEWS_FEEDS.items()]
    tasks.append((STORE_KEY, f"Posting `game_{STORE_KEY}`", STORE_ETA))
    for key in _xcom_keys():
        tasks.append((key, f"Posting `X - @{key.removeprefix('xcom-')}`", XCOM_ETA))
    return tasks


async def run_all_feeds(bot, progress) -> None:
    # Noticias del juego + tienda, con progreso dinámico
    jobs = list(NEWS_FEEDS.items()) + [(STORE_KEY, None)]

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
        for key in _xcom_keys():
            progress.failure(key)
        log(f"Feed XCom error: {e}", "feed", level="CRIT", show=False)

    # Resumen "lo último" → sys_save/last.json y GitHub (nunca debe romper los feeds)
    try:
        await publish_latest()
    except Exception as e:
        log(f"Feed publish error: {type(e).__name__}: {e}", "feed", level="CRIT", show=False)
