"""
Publica un resumen de lo último del juego en un repo de GitHub.

Se ejecuta al final de cada ciclo de feeds (ver __base.run_all_feeds) y hace:

    1. Lee las noticias ya escaneadas (sys_save/http/news.json y xcom.json).
    2. Extrae las fechas de cada noticia (schedule_*).
    3. Arma las 6 entradas de "lo último" y las guarda en sys_save/last.json:
         banner_next_leave  próximo banner (gacha) en irse
         banner_latest      último banner en llegar
         event_next_leave   próximo evento en irse
         event_latest       último evento en llegar
         service_latest     último MANTENIMIENTO / ACTUALIZACIÓN
         tweet_latest       último tweet de @Kj8_TheGame_en
       Cada una con título, URL de la fuente e imagen (miniatura en base64).
    4. Sube el archivo al repo SOLO si cambió algo real (checksum sin imagen).

Nada de esto debe romper los feeds: cualquier error se registra y se sigue.

.env:
    git_news_folder = usuario/repo            (archivo en la raíz del repo)
                    = usuario/repo/carpeta    (archivo dentro de esa carpeta)
    git_news_token  = token fine-grained con permiso "Contents: Read and write"
    git_news_branch = (opcional) rama; por defecto la rama principal
"""
import asyncio
import base64
import hashlib
import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from logger import log

from .__feed import as_int, load_json, save_json

# -------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------
NEWS_FILE = "sys_save/http/news.json"
XCOM_FILE = "sys_save/http/xcom.json"
LAST_FILE = "sys_save/last.json"
REMOTE_NAME = "last.json"

TWEET_ACCOUNT = "kj8_thegame_en"
NEWS_LINK = "https://info.kj8-thegame.com/news/{uuid}?language=en"
TWEET_IMAGE = "https://fxtwitter.com/i/status/{uuid}.png"

THUMB_SIZE = 480            # px (lado mayor)
THUMB_QUALITY = 70
IMAGE_TIMEOUT = 15
GITHUB_TIMEOUT = 20
GITHUB_API = "https://api.github.com"
HEADERS = {"User-Agent": "kaijuno8_feed_testing | Discord: @mnight4"}

ROLES = (
    "banner_next_leave",
    "banner_latest",
    "event_next_leave",
    "event_latest",
    "service_latest",
    "tweet_latest",
)


def _env(name: str) -> str:
    return (os.getenv(name.upper()) or os.getenv(name.lower()) or "").strip()


# -------------------------------------------------
# FECHAS (schedule_*) A PARTIR DE article_unix
# -------------------------------------------------
def schedule_for(article: dict) -> Dict[str, Optional[int]]:
    """
    maintenance / update : schedule_start
    event                : schedule_start, schedule_leave
    gacha                : schedule_start, schedule_pull_end, schedule_sell_end

    Las reglas del gacha son las mismas que usa feed_news.build_gacha_info_text.
    Lo que no se pueda deducir queda en None (mejor vacío que inventado).
    """
    kind = (article.get("article_type") or "").lower()
    unix: List[int] = sorted({as_int(u) for u in (article.get("article_unix") or []) if as_int(u) > 0})
    first = unix[0] if unix else None

    if kind in ("maintenance", "update"):
        return {"schedule_start": first}

    if kind == "event":
        return {"schedule_start": first, "schedule_leave": unix[-1] if len(unix) >= 2 else None}

    if kind == "gacha":
        text = "\n".join(str(i) for i in (article.get("article_item") or [])).lower()
        pull = "__availability period__" in text
        shop = "exchange period" in text
        out = {"schedule_start": first, "schedule_pull_end": None, "schedule_sell_end": None}
        if pull and shop and len(unix) == 3:        # release, gacha leave, store leave
            out["schedule_pull_end"], out["schedule_sell_end"] = unix[1], unix[2]
        elif pull and not shop and len(unix) == 3:  # release, event leave, gacha leave
            out["schedule_pull_end"] = unix[2]
        elif pull and not shop and len(unix) == 2:  # release, gacha leave
            out["schedule_pull_end"] = unix[1]
        return out

    return {}


# -------------------------------------------------
# ENTRADAS
# -------------------------------------------------
def _news_entry(article: dict) -> dict:
    uuid = str(article.get("article_uuid") or "")
    entry = {
        "id": uuid,
        "type": (article.get("article_type") or "").lower(),
        "title": article.get("article_name") or "",
        "url": NEWS_LINK.format(uuid=uuid),
        "posted": as_int(article.get("article_time")),
        "image_src": article.get("article_logo"),     # solo para descargar; no se publica
    }
    entry.update(schedule_for(article))
    return entry


def _tweet_entry(xcom: dict) -> Optional[dict]:
    account = next((v for k, v in xcom.items() if k.lower() == TWEET_ACCOUNT), None)
    posts = (account or {}).get("status") or {}
    if not posts:
        return None
    post = max(posts.values(), key=lambda p: as_int(p.get("uuid")))
    uuid = str(post.get("uuid") or "")
    # Título: lo primero que sale antes del primer doble salto de línea.
    text = (post.get("text") or "").replace("\r\n", "\n").strip()
    return {
        "id": uuid,
        "type": "tweet",
        "title": text.split("\n\n", 1)[0].strip(),
        "url": post.get("link") or f"https://x.com/i/status/{uuid}",
        "image_src": TWEET_IMAGE.format(uuid=uuid),
    }


def select_entries(news: Dict[str, dict], xcom: Dict[str, Any], now: int) -> Dict[str, Optional[dict]]:
    """Elige las 6 entradas. Función pura (sin red ni disco) para poder probarla."""
    entries = [_news_entry(a) for a in news.values() if a.get("article_uuid")]

    def of(*types: str) -> List[dict]:
        return [e for e in entries if e["type"] in types]

    def latest(items: List[dict]) -> Optional[dict]:
        return max(items, key=lambda e: e["posted"], default=None)

    def next_leaving(items: List[dict], key: str) -> Optional[dict]:
        pending = [e for e in items if (e.get(key) or 0) > now]
        return min(pending, key=lambda e: e[key], default=None)

    banners, events = of("gacha"), of("event")
    return {
        "banner_next_leave": next_leaving(banners, "schedule_pull_end"),
        "banner_latest": latest(banners),
        "event_next_leave": next_leaving(events, "schedule_leave"),
        "event_latest": latest(events),
        "service_latest": latest(of("maintenance", "update")),
        "tweet_latest": _tweet_entry(xcom),
    }


# -------------------------------------------------
# IMÁGENES: miniatura en base64, descargada UNA sola vez por noticia
# -------------------------------------------------
def make_thumbnail(data: bytes) -> Optional[str]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            img.seek(0)
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            out = io.BytesIO()
            img.save(out, "WEBP", quality=THUMB_QUALITY, method=4)
    except Exception as e:
        log(f"[PUBLISH]: Thumbnail failed: {e}", "feed", level="CRIT", show=False)
        return None
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def download_thumbnail(url: Optional[str]) -> Optional[str]:
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=IMAGE_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return None
        return make_thumbnail(resp.content)
    except Exception as e:
        log(f"[PUBLISH]: Image download failed [{url}]: {e}", "feed", level="CRIT", show=False)
        return None


def attach_images(entries: Dict[str, Optional[dict]], previous: Dict[str, Optional[dict]]) -> None:
    """
    Reutiliza la miniatura de la ejecución anterior cuando el id no cambió
    (así el hash temporal de la URL original no importa). Solo descarga lo nuevo.
    """
    cache = {
        e["id"]: e["image"]
        for e in (previous or {}).values()
        if isinstance(e, dict) and e.get("id") and e.get("image")
    }
    fetched: Dict[str, Optional[str]] = {}
    for entry in entries.values():
        if not entry:
            continue
        uid = entry["id"]
        if uid not in cache and uid not in fetched:
            fetched[uid] = download_thumbnail(entry.get("image_src"))
        entry["image"] = cache.get(uid) or fetched.get(uid)
        entry.pop("image_src", None)


# -------------------------------------------------
# CHECKSUM (sin imágenes: sus URLs/bytes no deben provocar subidas)
# -------------------------------------------------
def checksum(news_list: Dict[str, Optional[dict]]) -> str:
    stable = {}
    for role in ROLES:
        e = news_list.get(role)
        if e is None:
            stable[role] = None
            continue
        item = {k: v for k, v in e.items() if k != "image"}
        item["has_image"] = bool(e.get("image"))
        stable[role] = item
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# -------------------------------------------------
# GITHUB (API de Contents: no requiere git instalado)
# -------------------------------------------------
def _target():
    folder = _env("git_news_folder").strip("/")
    token = _env("git_news_token")
    parts = [p for p in folder.split("/") if p]
    if len(parts) < 2 or not token:
        return None
    repo = "/".join(parts[:2])
    path = "/".join(parts[2:] + [REMOTE_NAME])
    return repo, path, token, _env("git_news_branch") or None


def upload(text: str) -> bool:
    target = _target()
    if target is None:
        log("[PUBLISH]: git_news_folder / git_news_token not set; upload skipped.", "feed", show=False)
        return False
    repo, path, token, branch = target
    url = f"{GITHUB_API}/repos/{repo}/contents/{path}"
    headers = {
        **HEADERS,
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    params = {"ref": branch} if branch else None
    content = base64.b64encode(text.encode("utf-8")).decode("ascii")

    for attempt in (1, 2):
        try:
            sha = None
            got = requests.get(url, headers=headers, params=params, timeout=GITHUB_TIMEOUT)
            if got.status_code == 200:
                sha = got.json().get("sha")
            elif got.status_code != 404:
                log(f"[PUBLISH]: GitHub GET failed [{got.status_code}]", "feed", level="CRIT", show=False)
                return False

            body: Dict[str, Any] = {"message": "Update latest game news", "content": content}
            if sha:
                body["sha"] = sha
            if branch:
                body["branch"] = branch
            put = requests.put(url, headers=headers, json=body, timeout=GITHUB_TIMEOUT)
            if put.status_code in (200, 201):
                return True
            if put.status_code in (409, 422) and attempt == 1:
                continue                                  # el sha cambió entre medias: reintento
            log(f"[PUBLISH]: GitHub PUT failed [{put.status_code}] {put.text[:200]}", "feed", level="CRIT", show=False)
            return False
        except Exception as e:
            log(f"[PUBLISH]: GitHub error: {type(e).__name__}", "feed", level="CRIT", show=False)
            return False
    return False


# -------------------------------------------------
# FLUJO PRINCIPAL
# -------------------------------------------------
def publish_sync(now: Optional[int] = None) -> str:
    """Devuelve 'unchanged', 'uploaded', 'saved' (solo local) o 'failed'."""
    now = int(now if now is not None else time.time())
    news = load_json(NEWS_FILE, {})
    xcom = load_json(XCOM_FILE, {})
    if not news and not xcom:
        return "unchanged"

    previous = load_json(LAST_FILE, {})
    entries = select_entries(news, xcom, now)
    attach_images(entries, previous.get("news_list") or {})

    new_sum = checksum(entries)
    sent_sum = previous.get("last_checksum_sent")
    if new_sum == sent_sum:
        return "unchanged"

    payload = {"last_checksum_sent": new_sum, "news_list": entries}
    ok = upload(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))

    # Si la subida falla (o no hay token) se guarda lo nuevo pero con el checksum
    # anterior: en el próximo ciclo se vuelve a intentar.
    local = {"last_checksum_sent": new_sum if ok else sent_sum, "news_list": entries}
    if local != previous:
        save_json(LAST_FILE, local)
    return "uploaded" if ok else ("saved" if _target() is None else "failed")


async def publish_latest() -> str:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, publish_sync)
    log(f"[PUBLISH]: {result}", "feed", show=False)
    return result
