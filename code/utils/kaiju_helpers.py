import discord
from datetime import datetime

def get_accent_color(article_type: str) -> int:
    t = article_type.lower()
    colors = {
        "maintenance": 0x455a64,
        "important": 0xe53935,
        "update": 0x1e88e5,
        "event": 0x43a047,
        "gacha": 0x8e24aa,
        "news": 0x546e7a,
        "known issue": 0xfb8c00,
    }
    return colors.get(t, 0xaaaaaa)


def get_emoji(article_type: str) -> str:
    t = article_type.lower()
    emojis = {
        "maintenance": "🚧",
        "important": "⚠️",
        "update": "📥",
        "event": "🎉",
        "gacha": "🎫",
        "news": "📰",
        "known issue": "🔥",
    }
    return emojis.get(t, "⁉️")


def get_relative_time(unix_time: int) -> str:
    diff = int(datetime.utcnow().timestamp()) - unix_time
    if diff < 0:
        return "0d"
    
    days = diff // 86400
    if days < 30:
        return f"{days}d"
    months = days // 30
    if months < 12:
        return f"{months}m"
    return f"{months//12}y"


def get_info_text(article_type: str, unix_time: int) -> str:
    rel = get_relative_time(unix_time)
    t = article_type.upper()
    return f"{rel} - {t}"