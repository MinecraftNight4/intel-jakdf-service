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


def fetchjson(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default.copy() if isinstance(default, dict) else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, dict) else default



def now_as_jst() -> datetime:
    return datetime.now(JST)

def now_as_unix() -> int:
    return int(time.time())

def date_2_unix(dt: datetime) -> int:
    return int(dt.astimezone(UTC).timestamp())



def generate_as_unix_day(h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_as_jst()
    target = n.replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return date_2_unix(target)

def generate_as_unix_week(weekday: int = 7, h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_as_jst()
    target_weekday = (weekday - 1) % 7
    days_ahead = (target_weekday - n.weekday()) % 7
    target = (n + timedelta(days=days_ahead)).replace(hour=h, minute=m, second=s, microsecond=0)
    if target <= n:
        target += timedelta(weeks=1)
    return date_2_unix(target)

def generate_as_unix_month(h: int = 0, m: int = 0, s: int = 0) -> int:
    n = now_as_jst()
    last_day = monthrange(n.year, n.month)[1]
    target = n.replace(day=last_day, hour=h, minute=m, second=s, microsecond=0)
    if target <= n:
        if n.month == 12:
            next_year, next_month = n.year + 1, 1
        else:
            next_year, next_month = n.year, n.month + 1
        last_day = monthrange(next_year, next_month)[1]
        target = datetime(next_year, next_month, last_day, h, m, s, tzinfo=JST)
    return date_2_unix(target)



def format_time_view(ts: int, relative: bool = False, style: str = "f") -> str:
    if relative:
        return f"<t:{ts}:R>"
    return f"<t:{ts}:{style}>"

def format_text_view(ts: int, pass_txt: str, ends_txt: str = "") -> str:
    now = now_as_unix()
    txt = ends_txt if ts < now else pass_txt
    return txt.replace("{time}", str(ts))

def format_full_text(art: dict) -> str:
    parts = []
    items = art.get("article_item") or []
    if isinstance(items, list):
        parts.extend(str(x) for x in items)
    return "".join(parts).lower()



def event_get_unimaterial(art: dict) -> str:
    txt = format_full_text(art)
    ls1 = ["armored", "caudata", "fungal", "wyvern", "wolf", "paraves", "plant", "mole", "lizard", "bovine", "spider", "wyvern", "ant"]
    ls2 = ["α", "β"]
    out = []
    for da1 in ls1:
        for da2 in ls2:
            if (f"[{da1}-type unipart {da2}]") in txt:
                out.append(f"{da1.upper} {da2}")
    return (", ".join(out).upper())



def calendar_unix_list(limit: int = 3) -> List[Tuple[int, str]]:
    rmap = fetchjson(RMAP_FILE, {})
    candidates = []
    for data in rmap.values():
        formats = data.get("format", {})
        for ts_str, text in formats.items():
            try:
                ts = int(ts_str)
                if ts > now_as_unix():
                    candidates.append((ts, text))
            except ValueError:
                continue
    candidates.sort(key=lambda x: x[0])
    return candidates[:limit]

def calendar_rmap_view() -> Optional[str]:
    rmap = fetchjson(RMAP_FILE, {})
    if rmap:
        best_id = max(rmap.keys(), key=lambda k: rmap[k].get("processed_at", 0))
        return rmap[best_id].get("display")
    xcom = fetchjson(XCOM_FILE, {})
    for account in xcom.values():
        roadmaps = account.get("roadmap", {})
        if roadmaps:
            best = max(roadmaps.values(), key=lambda r: r.get("post_at", 0))
            return best.get("preview")
    return None



def status_show_warn(art: dict) -> bool:
    text = format_full_text(art)
    if "__maintenance time__\n<t:" in text:
        return True
    if "the data update has been successfully completed" in text:
        return False
    if "update is now available." in text:
        return False
    return True

def status_show_display() -> bool:
    news = fetchjson(NEWS_FILE, {})
    candidate_data = None
    candidate_time = 0
    
    for art in news.values():
        if art.get("article_type") in ("update", "maintenance"):
            art_time = art.get("article_time", 0)
            if art_time > candidate_time:
                candidate_time = art_time
                candidate_data = art

    if candidate_data:
        if not status_show_warn(candidate_data):
            return False
        else:
            return True
    return False

