import json
import os
from typing import Dict, Any
from logger import info, warn, crit, log

import discord
from discord.ext import commands

XCOM_FILE  = "sys_save/request_xcom.json"
SETUP_FILE = "sys_save/feed_system_setup.json"
DATA_FILE  = "sys_save/feed_system_data.json"


def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default.copy() if isinstance(default, dict) else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, dict) else default


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


async def process_feed_xcom(bot: commands.Bot) -> int:
    """
    Lee request_xcom.json → compara hashes → publica posts nuevos.
    Mensaje: [`🔗`](https://fxtwitter.com/i/status/{UUID}) <{URL}>
    """
    xcom_data: Dict[str, Any] = load_json(XCOM_FILE, {})
    setup = load_json(SETUP_FILE, {})
    data  = load_json(DATA_FILE, {})

    total_new = 0
    accounts = list(xcom_data.keys())

    if not accounts:
        log("[FEED - XCOM]: No accounts found", "feed", level="WARN", show=False)
        return 0

    log(f"[FEED - XCOM]: Processing {len(accounts)} accounts...", "feed", show=False)

    for account in accounts:
        namespace = f"xcom-{account.lower()}"   # ej: xcom-kj8_thegame_en

        if namespace not in data:
            data[namespace] = []

        already_sent = set(data[namespace])
        status_posts = (xcom_data.get(account) or {}).get("STATUS") or {}

        # Hashes actuales
        current_hashes = set()
        posts_by_hash = {}

        for uuid, post in status_posts.items():
            h = post.get("HASH")
            if h:
                current_hashes.add(h)
                posts_by_hash[h] = post

        new_hashes = current_hashes - already_sent

        if not new_hashes:
            data[namespace] = list(current_hashes)
            continue

        new_posts = [posts_by_hash[h] for h in new_hashes]
        # Ordenar por UUID descendente (más recientes primero, aproximado)
        new_posts.sort(key=lambda p: p.get("UUID") or "", reverse=True)

        log(f"[FEED - XCOM | @{account}]: {len(new_posts)} new posts", "feed", show=False)

        feed_channels = setup.get(namespace, {})
        if not feed_channels:
            log(f"[FEED - XCOM | @{account}]: No channels for '{namespace}'", "feed", level="WARN", show=False)
            data[namespace] = list(current_hashes)
            continue

        for guild_id, entry in feed_channels.items():
            channel_id = entry.get("channel")
            if not channel_id:
                continue

            channel = bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await bot.fetch_channel(int(channel_id))
                except Exception:
                    log(f"- [{channel_id}]: FAILURE", "feed", level="CRIT", show=False)
                    continue

            log(f"- [{channel_id}]: SUCCESS", "feed", show=False)
            can_publish = bool(entry.get("publish", False))
            is_announcement = getattr(channel, "is_news", lambda: False)()

            for post in new_posts:
                uuid = post.get("UUID") or ""
                url  = post.get("URL") or ""

                content = f"[`🔗`](https://fxtwitter.com/i/status/{uuid}) <{url}>"

                try:
                    msg = await channel.send(content=content)
                    log(f"  - [SEND: SUCCESS] | {uuid}", "feed", show=False)

                    if can_publish and is_announcement:
                        try:
                            await msg.publish()
                            log(f"      ⤷ CROSSPOST: SUCCESS", "feed", show=False)
                        except Exception as e:
                            log(f"      ⤷ CROSSPOST: FAILURE | {e}", "feed", level="WARN", show=False)

                    total_new += 1
                except Exception as e:
                    log(f"  - [SEND: FAILURE] | {uuid} | {e}", "feed", level="CRIT", show=False)

            # Texto de ping opcional
            ping_text = entry.get("text")
            if ping_text and str(ping_text).strip():
                try:
                    await channel.send(content=str(ping_text).strip())
                    log(f"    ⤷ PING: SUCCESS | {ping_text}", "feed", show=False)
                except Exception as e:
                    log(f"    ⤷ PING: FAILURE | {e}", "feed", level="CRIT", show=False)

        data[namespace] = list(current_hashes)

    save_json(DATA_FILE, data)

    log(f"[FEED - XCOM]: [SENT x{total_new}]", "feed", show=False)
    log(f"[FEED - XCOM]: Thread closed.", "feed", show=False)
    log(f" ", "feed", show=False)
    return total_new