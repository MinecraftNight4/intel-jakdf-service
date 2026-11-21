from typing import Any, Dict, List
from discord.ext import commands
from logger import log

from . import __setup as feed_setup
from .__feed import (
    Message,
    as_int,
    commit_history,
    deliver,
    load_history,
    load_json,
)

# -------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------
XCOM_FILE = "sys_save/request_xcom.json"


def _make_post_message(post: dict) -> Message:
    post_uuid = post.get("uuid") or ""
    post_link = post.get("link") or ""
    content = f"[`🔗`](https://fxtwitter.com/i/status/{post_uuid}) <{post_link}>"
    return Message(
        uid=f"#{post.get('hash') or ''}",
        label=post_link,
        make=lambda: {"content": content},
    )


async def process_feed_xcom(bot: commands.Bot, progress=None) -> int:
    storage_news: Dict[str, Any] = load_json(XCOM_FILE, {})
    total_sent = 0

    accounts = list(storage_news.keys())
    log(f"[FEED - XCOM]: Creating {len(accounts)} instances...", "feed", show=False)

    for account in accounts:
        namespace = f"xcom-{account.lower()}"      # ← clave real (__setup / progreso)
        tag = f"XCOM @{account.upper()}"

        targets = feed_setup.targets(namespace)
        previous = load_history(namespace)
        already_sent = set(previous)
        posts: Dict[str, Any] = (storage_news.get(account) or {}).get("status") or {}

        # Indexar posts (sin hashes repetidos)
        catalog: Dict[str, dict] = {}
        for post in posts.values():
            h = post.get("hash")
            if h:
                catalog[h] = post
        current = list(catalog)

        # Lo nuevo, del más viejo al más nuevo (los id de x.com crecen con el tiempo)
        fresh: List[dict] = [catalog[h] for h in current if h not in already_sent]
        fresh.sort(key=lambda p: as_int(p.get("uuid")))

        log(f"[FEED - XCOM]: [TARGET: @{account.upper()}] [CHANNELS: {len(targets)}] [ARTICLES: {len(fresh)}/{len(posts)}]", "feed", show=False)

        # Si no hay nada que publicar → saltar
        if not fresh or not targets:
            commit_history(namespace, previous, current, keep=len(posts), replace=True)
            if progress:
                progress.start_task(namespace)
                progress.success(namespace)
            log(f"[FEED - XCOM]: [TARGET: @{account.upper()}] SECTION SKIPPED...", "feed", show=False)
            continue

        if progress:
            progress.start_task(namespace)

        messages = [_make_post_message(p) for p in fresh]
        sent = await deliver(bot, tag, targets, messages, progress=progress, progress_key=namespace)
        total_sent += sent

        # Marcar esta cuenta como terminada
        if progress:
            progress.success(namespace)

        commit_history(namespace, previous, current, keep=len(posts), replace=False)
        log(f"[FEED - XCOM]: [TARGET: @{account.upper()}] [SENT x{sent}]", "feed", show=False)

    log(f"[FEED - XCOM]: [SENT: {total_sent}]", "feed", show=False)
    log("[FEED - XCOM]: THREAD CLOSED.", "feed", show=False)
    return total_sent
