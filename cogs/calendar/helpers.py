# cogs/calendar/helpers.py
import json
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from calendar import monthrange
from typing import Dict, Any, List, Optional, Tuple

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc

NEWS_FILE = "sys_save/request_news.json"
XCOM_FILE = "sys_save/request_xcom.json"
RMAP_FILE = "sys_save/request_rmap.json"
PUBLIC_COOLDOWN = 60


def now_jst() -> datetime:
    return datetime.now(JST)

def now_unix() -> int:
    return int(time.time())

def to_unix(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp())

def GenerateUnixDay(h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_jst()
    target = n.replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return to_unix(target)

def GenerateUnixWeek(weekday: int = 7, h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_jst()
    target_weekday = (weekday - 1) % 7
    days_ahead = (target_weekday - n.weekday()) % 7
    target = (n + timedelta(days=days_ahead)).replace(
        hour=h, minute=m, second=s, microsecond=0
    )
    if target <= n:
        target += timedelta(weeks=1)
    return to_unix(target)

def GenerateUnixMonth(h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_jst()
    last_day = monthrange(n.year, n.month)[1]
    target = n.replace(day=last_day, hour=h, minute=m, second=s, microsecond=0)

    if target <= n:
        if n.month == 12:
            next_year, next_month = n.year + 1, 1
        else:
            next_year, next_month = n.year, n.month + 1
        last_day = monthrange(next_year, next_month)[1]
        target = datetime(next_year, next_month, last_day, h, m, s, tzinfo=JST)

    return to_unix(target)

def format_ts(ts: int, relative: bool = False, style: str = "f") -> str:
    if relative:
        return f"<t:{ts}:R>"
    return f"<t:{ts}:{style}>"

def FlavorTextOnTime(ts: int, pass_txt: str, ends_txt: str = "") -> str:
    now = now_unix()
    txt = ends_txt if ts < now else pass_txt
    return txt.replace("{time}", str(ts))

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

def get_upcoming_events(limit: int = 3) -> List[Tuple[int, str]]:
    rmap = load_json(RMAP_FILE, {})
    candidates = []
    for data in rmap.values():
        formats = data.get("format", {})
        for ts_str, text in formats.items():
            try:
                ts = int(ts_str)
                if ts > now_unix():
                    candidates.append((ts, text.strip()))
            except ValueError:
                continue
    candidates.sort(key=lambda x: x[0])
    return candidates[:limit]

def get_best_roadmap_image() -> Optional[str]:
    rmap = load_json(RMAP_FILE, {})
    if rmap:
        best_id = max(rmap.keys(), key=lambda k: rmap[k].get("processed_at", 0))
        return rmap[best_id].get("display")
    xcom = load_json(XCOM_FILE, {})
    for account in xcom.values():
        roadmaps = account.get("roadmap", {})
        if roadmaps:
            best = max(roadmaps.values(), key=lambda r: r.get("post_at", 0))
            return best.get("preview")
    return None

def has_active_maintenance() -> bool:
    news = load_json(NEWS_FILE, {})
    now = now_unix()
    for art in news.values():
        t = (art.get("article_type") or "").lower()
        if t in ("update", "maintenance"):
            unixes = art.get("article_unix") or []
            if unixes and max(unixes) > now:
                return True
    return False