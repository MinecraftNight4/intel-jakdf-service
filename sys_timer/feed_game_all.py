import json
import os
import io
import math
from typing import Dict, Any, List, Optional, Tuple

import aiohttp
import discord
from discord.ext import commands

# Importamos la vista desde el cog
from cogs.news import FeedNewsPageView, FEED_ITEMS_PER_PAGE

NEWS_FILE   = "sys_save/request_news.json"
SETUP_FILE  = "sys_save/feed_system_setup.json"
DATA_FILE   = "sys_save/feed_system_data.json"


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


async def download_image(url: str) -> Optional[Tuple[io.BytesIO, str]]:
    """Descarga una imagen y la devuelve como (BytesIO, filename)."""
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
                ext = url.split("?")[0].split(".")[-1].lower()
                if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
                    ext = "png"
                filename = f"feed_logo_{hash(url) % 100000}.{ext}"
                return io.BytesIO(data), filename
    except Exception as e:
        print(f"⚠️ [FEED] No se pudo descargar imagen: {e}")
        return None


async def process_feed_game_all(bot: commands.Bot) -> int:
    """
    Detecta noticias nuevas por hash y las publica en los canales
    configurados como feed_game_all.
    Devuelve la cantidad de noticias nuevas enviadas.
    """
    news: Dict[str, Any] = load_json(NEWS_FILE, {})
    setup = load_json(SETUP_FILE, {})
    data  = load_json(DATA_FILE, {})

    if "feed_game_all" not in data:
        data["feed_game_all"] = []

    already_sent = set(data["feed_game_all"])
    feed_channels = setup.get("feed_game_all", {})

    if not feed_channels:
        print("ℹ️ [FEED] No hay canales configurados para feed_game_all")
        return 0

    # Ordenar por más reciente primero
    articles = sorted(
        news.values(),
        key=lambda a: int(a.get("article_time", 0)),
        reverse=True
    )

    new_count = 0

    for article in articles:
        h = article.get("article_hash")
        if not h or h == "0" or h in already_sent:
            continue

        # --- Imagen persistente ---
        files: List[discord.File] = []
        logo_media = None
        logo_url = article.get("article_logo")

        if logo_url:
            result = await download_image(logo_url)
            if result:
                file_data, filename = result
                files.append(discord.File(file_data, filename=filename))
                logo_media = f"attachment://{filename}"

        view = FeedNewsPageView(
            article,
            items_per_page=FEED_ITEMS_PER_PAGE,
            logo_media=logo_media
        )

        # Enviar a todos los canales configurados
        for guild_id, entry in feed_channels.items():
            channel_id = entry.get("channel")
            if not channel_id:
                continue

            channel = bot.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await bot.fetch_channel(int(channel_id))
                except Exception:
                    print(f"❌ [FEED] No se pudo obtener canal {channel_id}")
                    continue

            content = entry.get("text")  # ping opcional
            try:
                # Reiniciar el puntero del BytesIO por si se reutiliza
                for f in files:
                    f.fp.seek(0)

                msg = await channel.send(
                    content=content,
                    view=view,
                    files=files if files else None
                )

                # Publicar (crosspost) si está activado
                if entry.get("publish") and hasattr(msg, "publish"):
                    try:
                        await msg.publish()
                    except Exception:
                        pass

                print(f"✅ [FEED] Enviado: {article.get('article_name')[:50]} → #{getattr(channel, 'name', channel_id)}")

            except Exception as e:
                print(f"❌ [FEED] Error enviando a {channel_id}: {e}")

        # Marcar como enviado
        data["feed_game_all"].append(h)
        already_sent.add(h)
        new_count += 1

        # Guardar después de cada noticia para no perder progreso
        save_json(DATA_FILE, data)

    return new_count