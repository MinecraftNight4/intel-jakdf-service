import asyncio
import base64
import hashlib
import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import requests
from PIL import Image, ImageOps
from logger import log

from .__feed import as_int, load_json, save_json

NEWS_FILE = "sys_save/http/news.json"
XCOM_FILE = "sys_save/http/xcom.json"
LAST_FILE = "sys_save/last.json"
REMOTE_NAME = "last.json"

TWEET_ACCOUNT = "kj8_thegame_en"
NEWS_LINK = "https://info.kj8-thegame.com/news/{uuid}?language=en&platform=jakdf_discord_application"

CANVAS_W = 640              # 16:9 exacto (640x360)
CANVAS_H = 360
THUMB_QUALITY = 75
IMAGE_TIMEOUT = 15
GITHUB_TIMEOUT = 20
GITHUB_API = "https://api.github.com"
HEADERS = {"User-Agent": "kaijuno8_feed_testing | Discord: @mnight4"}


def _env(name: str) -> str:
    return (os.getenv(name.upper()) or os.getenv(name.lower()) or "").strip()


def _resolve_expire(article: dict) -> int:
    kind = (article.get("article_type") or "").lower().strip()
    meta = article.get("metadata") or {}

    if kind == "gacha":
        candidates = [meta.get("banner"), meta.get("event"), meta.get("store")]
        valid = [int(x) for x in candidates if x]
        if valid:
            return max(valid)
    elif kind in ("maintenance", "update"):
        candidates = [meta.get("time_back"), meta.get("time_post")]
        valid = [int(x) for x in candidates if x]
        if valid:
            return max(valid)

    unix_list = [as_int(u) for u in (article.get("article_unix") or []) if as_int(u) > 0]
    if unix_list:
        return max(unix_list)
    return as_int(article.get("article_time"))


def _news_entry(article: dict) -> dict:
    uuid = str(article.get("article_uuid") or "")
    return {
        "entry": uuid,
        "text": (article.get("article_name") or "").strip(),
        "http": NEWS_LINK.format(uuid=uuid),
        "icon": None,
        "expire": _resolve_expire(article),
        "_posted": as_int(article.get("article_time")),
        "_image_src": article.get("article_logo"),
    }


def _tweet_entry(xcom: dict) -> Optional[dict]:
    account = next((v for k, v in xcom.items() if k.lower() == TWEET_ACCOUNT), None)
    posts = (account or {}).get("status") or {}
    if not posts:
        return None
    post = max(posts.values(), key=lambda p: as_int(p.get("uuid")))
    uuid = str(post.get("uuid") or "")
    text = (post.get("text") or "").replace("\r\n", "\n").strip()

    media_all = ((post.get("media") or {}).get("all") or {})
    img_src = media_all.get("thumbnail_url") or media_all.get("url")

    return {
        "entry": uuid,
        "text": text.split("\n\n", 1)[0].strip(),
        "http": post.get("link") or f"https://x.com/i/status/{uuid}",
        "icon": None,
        "expire": 0,
        "_image_src": img_src,
    }


def select_entries(news: Dict[str, dict], xcom: Dict[str, Any], now: int) -> Dict[str, Optional[dict]]:
    entries = [_news_entry(a) for a in news.values() if a.get("article_uuid")]

    def latest_by_types(*types: str) -> Optional[dict]:
        wanted = {t.lower() for t in types}
        matched = [
            e for e in entries
            if (news[e["entry"]].get("article_type") or "").lower().strip() in wanted
        ]
        return max(matched, key=lambda e: e["_posted"], default=None)

    # Última noticia de actualización/mantenimiento solo si existe y no ha expirado
    service_candidates = []
    for a in news.values():
        if not a.get("article_uuid"):
            continue
        if (a.get("article_type") or "").lower().strip() in ("maintenance", "update"):
            meta = a.get("metadata") or {}
            exp = max(
                [int(x) for x in (meta.get("time_back"), meta.get("time_post")) if x],
                default=0,
            )
            if exp > now:
                service_candidates.append(_news_entry(a))
    service_latest = max(service_candidates, key=lambda e: e["_posted"], default=None)

    result: Dict[str, Optional[dict]] = {
        "tweet_latest": _tweet_entry(xcom),
        "event_latest": latest_by_types("event"),
        "gacha_latest": latest_by_types("gacha"),
        "news_latest": latest_by_types("news", "", "unknown"),
    }
    if service_latest is not None:
        result["service_latest"] = service_latest

    return result


# -------------------------------------------------
# IMÁGENES: Conversión 16:9 con fondo negro
# -------------------------------------------------
def make_thumbnail_16_9(data: bytes) -> Optional[str]:
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.seek(0)
            rgb = img.convert("RGB")
            # Escala manteniendo proporción dentro de 640x360 y rellena bandas con negro (#000000)
            fitted = ImageOps.pad(
                rgb,
                (CANVAS_W, CANVAS_H),
                method=Image.Resampling.LANCZOS,
                color=(0, 0, 0),
                centering=(0.5, 0.5),
            )
            out = io.BytesIO()
            fitted.save(out, "WEBP", quality=THUMB_QUALITY, method=4)
    except Exception as e:
        log(f"[PUBLISH]: Thumbnail 16:9 failed: {e}", "feed", level="CRIT", show=False)
        return None
    return "data:image/webp;base64," + base64.b64encode(out.getvalue()).decode("ascii")


def download_thumbnail(url: Optional[str]) -> Optional[str]:
    if not url or not str(url).startswith(("http://", "https://")):
        return None
    try:
        resp = requests.get(url, headers=HEADERS, timeout=IMAGE_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200 or not resp.content:
            return None
        return make_thumbnail_16_9(resp.content)
    except Exception as e:
        log(f"[PUBLISH]: Image download failed [{url}]: {e}", "feed", level="CRIT", show=False)
        return None


def attach_images(entries: Dict[str, Optional[dict]], previous: Dict[str, Optional[dict]]) -> None:
    """
    Solo descarga y convierte a 16:9 si el 'entry' cambió respecto a la ejecución previa.
    """
    cache = {
        e["entry"]: e["icon"]
        for e in (previous or {}).values()
        if isinstance(e, dict) and e.get("entry") and e.get("icon")
    }
    fetched: Dict[str, Optional[str]] = {}
    for item in entries.values():
        if not item:
            continue
        uid = item["entry"]
        if uid not in cache and uid not in fetched:
            fetched[uid] = download_thumbnail(item.get("_image_src"))
        item["icon"] = cache.get(uid) or fetched.get(uid)
        item.pop("_image_src", None)
        item.pop("_posted", None)


def checksum(news_list: Dict[str, Optional[dict]]) -> str:
    stable = {}
    for key, e in news_list.items():
        if e is None:
            stable[key] = None
            continue
        item = {k: v for k, v in e.items() if k != "icon"}
        item["has_icon"] = bool(e.get("icon"))
        stable[key] = item
    raw = json.dumps(stable, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# -------------------------------------------------
# GITHUB API
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
        log("[PUBLISH]: git_news_folder / git_news_token not set; upload skipped.", "feed", level="WARN", show=False)
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
                log(f"[PUBLISH]: GitHub GET failed [{got.status_code}] {got.text[:250]}", "feed", level="CRIT", show=False)
                return False

            body: Dict[str, Any] = {"message": "Update latest game news", "content": content}
            if sha:
                body["sha"] = sha
            if branch:
                body["branch"] = branch
            put = requests.put(url, headers=headers, json=body, timeout=GITHUB_TIMEOUT)
            if put.status_code in (200, 201):
                log(f"[PUBLISH]: GitHub upload OK -> {repo}/{path}", "feed", show=False)
                return True
            if put.status_code in (409, 422) and attempt == 1:
                continue
            log(f"[PUBLISH]: GitHub PUT failed [{put.status_code}] {put.text[:250]}", "feed", level="CRIT", show=False)
            return False
        except Exception as e:
            log(f"[PUBLISH]: GitHub error: {type(e).__name__}: {e}", "feed", level="CRIT", show=False)
            return False
    return False


def publish_sync(now: Optional[int] = None) -> str:
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

    local = {"last_checksum_sent": new_sum if ok else sent_sum, "news_list": entries}
    if local != previous:
        save_json(LAST_FILE, local)
    return "uploaded" if ok else ("saved" if _target() is None else "failed")


async def publish_latest() -> str:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, publish_sync)
    log(f"[PUBLISH]: {result}", "feed", show=False)
    return result