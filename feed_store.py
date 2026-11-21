"""
Almacenamiento de la configuración de feeds (sys_save/feed_system_setup.json).

Estructura (schema 2)
---------------------
{
  "schema": 2,
  "allow_feed_commands": [123456789012345678],      # guilds con /feed habilitado
  "guilds": {
    "<guild_id>": [                                 # máx. MAX_FEEDS_PER_GUILD
      {"type": "feed_game_event", "channel": 111, "publish": false, "text": "..."},
      {"type": "feed_game_event", "channel": 222, "publish": true},
      {"type": "xcom-kj8_thegame_en", "channel": 333, "publish": false}
    ]
  }
}

- Un "feed" es la combinación (type, channel): el mismo tipo puede ir a varios
  canales del mismo guild, pero no dos veces al mismo canal.
- El límite se cuenta por guild, sumando feeds de cualquier tipo.
- El formato anterior (schema 1: {feed_type: {guild_id: {...}}}) se migra solo
  la primera vez que se carga, dejando un respaldo en <archivo>.v1.bak.
"""
import json
import os
import shutil
from typing import Dict, List, Optional, Tuple

from logger import log

FEEDS_FILE = "sys_save/feed_system_setup.json"
SCHEMA_VERSION = 2
MAX_FEEDS_PER_GUILD = 15

_RESERVED_KEYS = {"schema", "allow_feed_commands", "guilds"}


# ============================================================
# Carga / guardado
# ============================================================
def _empty() -> dict:
    return {"schema": SCHEMA_VERSION, "allow_feed_commands": [], "guilds": {}}


def _migrate_v1(old: dict) -> dict:
    """{feed_type: {guild_id: {channel, publish, text}}} → schema 2."""
    new = _empty()
    allowed = old.get("allow_feed_commands")
    new["allow_feed_commands"] = allowed if isinstance(allowed, list) else []

    moved = 0
    for feed_type, by_guild in old.items():
        if feed_type in _RESERVED_KEYS or not isinstance(by_guild, dict):
            continue
        for guild_id, entry in by_guild.items():
            if not isinstance(entry, dict) or not entry.get("channel"):
                continue
            item = {
                "type": feed_type,
                "channel": int(entry["channel"]),
                "publish": bool(entry.get("publish", False)),
            }
            if entry.get("text"):
                item["text"] = str(entry["text"])
            new["guilds"].setdefault(str(guild_id), []).append(item)
            moved += 1

    log(f"[FEED STORE]: Migrated schema 1 → 2 ({moved} feed(s))", "feed", show=False)
    return new


def _normalize(data: dict) -> dict:
    allowed = data.get("allow_feed_commands")
    if not isinstance(allowed, list):
        data["allow_feed_commands"] = []
    guilds = data.get("guilds")
    if not isinstance(guilds, dict):
        data["guilds"] = {}
    data["schema"] = SCHEMA_VERSION
    return data


def load() -> dict:
    if not os.path.exists(FEEDS_FILE):
        return _empty()
    try:
        with open(FEEDS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        log(f"[FEED STORE]: LOAD FAILURE | {e}", "feed", level="CRIT", show=False)
        # Evita que el próximo guardado pise (y pierda) un archivo dañado.
        try:
            shutil.copyfile(FEEDS_FILE, FEEDS_FILE + ".corrupt.bak")
        except Exception:
            pass
        return _empty()

    if not isinstance(raw, dict):
        return _empty()

    if raw.get("schema") == SCHEMA_VERSION:
        return _normalize(raw)

    # Schema 1 → migrar, respaldar el original y guardar.
    migrated = _migrate_v1(raw)
    try:
        backup = FEEDS_FILE + ".v1.bak"
        if not os.path.exists(backup):
            shutil.copyfile(FEEDS_FILE, backup)
    except Exception as e:
        log(f"[FEED STORE]: BACKUP FAILURE | {e}", "feed", level="WARN", show=False)
    save(migrated)
    return migrated


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(FEEDS_FILE), exist_ok=True)
    tmp = FEEDS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, FEEDS_FILE)  # escritura atómica


# ============================================================
# Consultas
# ============================================================
def guild_entries(guild_id) -> List[dict]:
    return list(load()["guilds"].get(str(guild_id), []))


def targets(feed_type: str) -> Dict[str, dict]:
    """
    Todos los destinos de un tipo de feed, en la forma que ya consumen los
    módulos de posteo: {clave_única: {"channel", "publish", "text"}}.
    La clave es "<guild_id>:<channel_id>" (solo se usa como etiqueta).
    """
    out: Dict[str, dict] = {}
    for guild_id, entries in load()["guilds"].items():
        for entry in entries:
            if entry.get("type") == feed_type and entry.get("channel"):
                out[f"{guild_id}:{entry['channel']}"] = entry
    return out


# ============================================================
# Modificaciones
# ============================================================
def add_or_update(
    guild_id,
    feed_type: str,
    channel_id: int,
    publish: bool = False,
    text: Optional[str] = None,
) -> Tuple[str, int]:
    """
    Devuelve (resultado, total_en_guild) donde resultado es
    "added", "updated" o "limit" (no se guardó nada).
    """
    data = load()
    entries: List[dict] = data["guilds"].setdefault(str(guild_id), [])

    entry = {"type": feed_type, "channel": int(channel_id), "publish": bool(publish)}
    if text and text.strip():
        entry["text"] = text.replace("\\n", "\n")[:1000]

    for i, current in enumerate(entries):
        if current.get("type") == feed_type and current.get("channel") == int(channel_id):
            entries[i] = entry
            save(data)
            return "updated", len(entries)

    if len(entries) >= MAX_FEEDS_PER_GUILD:
        return "limit", len(entries)

    entries.append(entry)
    save(data)
    return "added", len(entries)


def would_exceed_limit(guild_id, feed_type: str, channel_id: int) -> bool:
    """True si crear este feed (que aún no existe) superaría el límite."""
    entries = guild_entries(guild_id)
    exists = any(e.get("type") == feed_type and e.get("channel") == int(channel_id) for e in entries)
    return (not exists) and len(entries) >= MAX_FEEDS_PER_GUILD


def remove(guild_id, feed_type: str, channel_id: int) -> bool:
    data = load()
    entries: List[dict] = data["guilds"].get(str(guild_id), [])
    kept = [
        e for e in entries
        if not (e.get("type") == feed_type and e.get("channel") == int(channel_id))
    ]
    if len(kept) == len(entries):
        return False

    if kept:
        data["guilds"][str(guild_id)] = kept
    else:
        data["guilds"].pop(str(guild_id), None)
    save(data)
    return True
