# cogs/profile/store.py
"""Datos de /profile. Sin dependencias de discord, para poder probarlo solo.

- Roster (lista de personajes): ``sys_save/profile/roster.json``, se edita a mano.
  ``[{"name": "[Titulo] Nombre", "icon": "🔥", "uuid": 1}, ...]``
  El ``uuid`` es lo que se guarda por usuario: se puede renombrar un personaje o cambiar su
  icono sin perder datos. Los cambios al archivo se detectan solos (sin reiniciar el bot).
- Progreso de usuarios: SQLite (``sys_save/profile.db``), libreria estandar de Python.
  Los perfiles sin cambios durante ``INACTIVE_DAYS`` se borran (``prune``).
"""
import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Dict, List, Optional, Tuple

ROSTER_FILE = "sys_save/profile/roster.json"
DB_FILE = "sys_save/profile/profile.db"

MAX_DUPES = 6
LOCKED = -1                 # "estado" para quitar el personaje (bloqueado)
INACTIVE_DAYS = 365

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    INTEGER PRIMARY KEY,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_updated ON users(updated_at);
CREATE TABLE IF NOT EXISTS owned (
    user_id   INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    character INTEGER NOT NULL,
    dupes     INTEGER NOT NULL CHECK (dupes BETWEEN 0 AND 6),
    PRIMARY KEY (user_id, character)
) WITHOUT ROWID;
"""


PER_PAGE = 4        # personajes por pestana del panel /profile edit


def _split_name(name: str) -> Tuple[str, str]:
    """``[Titulo] Nombre`` → (``[Titulo]``, ``Nombre``)."""
    head, sep, tail = name.partition("] ")
    return (head + "]", tail) if sep and head.startswith("[") else ("", name)


def _bracketed(text: str) -> str:
    text = (text or "").strip()
    return f"[{text.strip('[]')}]" if text else ""


class Roster:
    """Personajes de ``profile_roster.json`` (se recargan si el archivo cambia).

    Cada personaje: ``full_name`` (nombre base), ``prev_name`` (alias, el ``[Titulo]``),
    ``name`` (``[Titulo] Nombre``), ``icon`` y ``uuid``. Tambien se aceptan los nombres
    ``real_name``/``pref_name``, y basta con ``name`` para que se completen los demas.

    Al cargar el bot el archivo se reescribe con tres listas derivadas, que siempre se
    recalculan a partir de los personajes (editarlas a mano no sirve de nada):
      ``page_list``        uuid de los personajes de cada pestana del panel, ``PER_PAGE`` por pestana
      ``name_list``        nombres base (sin prefijo ni repetir) de cada pestana, en el mismo
                           orden que ``page_list``: el indice del panel solo los une con comas
      ``squad_name_list``  nombre base de CADA personaje, indexado por uuid: el de ``uuid`` esta en
                           ``squad_name_list[uuid - 1]`` (para /squad; hueco = "" si falta un uuid)
    """

    def __init__(self, path: str = ROSTER_FILE):
        self.path = path
        self._mtime = None
        self.raw: List[dict] = []                # en el orden del archivo
        self.items: List[dict] = []              # ordenados por personaje y luego por alias
        self.by_uuid: Dict[int, dict] = {}
        self.names: List[List[str]] = []         # = name_list
        self.pages: List[List[int]] = []         # = page_list
        self.squad_names: List[str] = []         # = squad_name_list
        self.reload_if_changed()

    def reload_if_changed(self) -> None:
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            return
        if mtime == self._mtime:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return                      # archivo a medio editar: se conserva la lista anterior
        entries = data.get("characters") if isinstance(data, dict) else data
        raw, seen = [], set()
        for entry in entries if isinstance(entries, list) else []:
            char = self._normalize(entry)
            if char and char["uuid"] not in seen:
                seen.add(char["uuid"])
                raw.append(char)
        self._mtime = mtime
        self.raw = raw
        self.items = sorted(raw, key=lambda c: (c["full_name"].lower(), c["name"].lower()))
        self.by_uuid = {c["uuid"]: c for c in self.items}
        self.pages = [[c["uuid"] for c in self.items[i:i + PER_PAGE]] for i in range(0, len(self.items), PER_PAGE)]
        self.names = [list(dict.fromkeys(self.by_uuid[u]["full_name"] for u in page)) for page in self.pages]
        top = max(self.by_uuid, default=0)
        self.squad_names = [self.by_uuid[u]["full_name"] if u in self.by_uuid else "" for u in range(1, top + 1)]

    @staticmethod
    def _normalize(entry) -> Optional[dict]:
        if not isinstance(entry, dict) or not isinstance(entry.get("uuid"), int):
            return None
        full = str(entry.get("full_name") or entry.get("real_name") or "").strip()
        prev = _bracketed(str(entry.get("prev_name") or entry.get("pref_name") or ""))
        name = str(entry.get("name") or "").strip()
        if name and not full:
            prev, full = _split_name(name) if not prev else (prev, _split_name(name)[1])
        if not full:
            return None
        char = {k: v for k, v in entry.items() if k not in ("real_name", "pref_name")}
        char.update(full_name=full, prev_name=prev, name=name or f"{prev} {full}".strip(),
                    icon=str(entry.get("icon") or "🔹"))
        # orden de claves estable: las nuevas primero, el resto como estaba
        order = ["full_name", "prev_name", "name", "icon", "uuid"]
        return {**{k: char[k] for k in order}, **{k: v for k, v in char.items() if k not in order}}

    def rewrite(self) -> bool:
        """Escribe el archivo con ``characters`` + las listas derivadas. True si cambio algo."""
        if self._mtime is None:                   # no hay archivo legible: no se inventa uno
            return False
        indent = lambda text: text.replace("\n", "\n\t")
        def rows(lists):                          # una pestana por linea
            return "[\n\t\t" + ",\n\t\t".join(json.dumps(item, ensure_ascii=False) for item in lists) + "\n\t]"

        def flat(items, per_line=4):                # un solo array, varios elementos por linea
            lines = [", ".join(json.dumps(x, ensure_ascii=False) for x in items[i:i + per_line])
                     for i in range(0, len(items), per_line)]
            return "[\n\t\t" + ",\n\t\t".join(lines) + "\n\t]"

        parts = [
            '"characters": ' + indent(json.dumps(self.raw, ensure_ascii=False, indent="\t")),
            '"page_list": ' + rows(self.pages),
            '"name_list": ' + rows(self.names),
            '"squad_name_list": ' + flat(self.squad_names),
        ]
        text = "{\n\t" + ",\n\t".join(parts) + "\n}\n"
        try:
            with open(self.path, encoding="utf-8", newline="") as fh:
                if fh.read().replace("\r\n", "\n") == text:
                    return False
        except OSError:
            pass
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, self.path)
        self._mtime = os.path.getmtime(self.path)
        return True


class ProfileStore:
    def __init__(self, roster_file: str = ROSTER_FILE, db_file: str = DB_FILE):
        self.roster = Roster(roster_file)
        self.roster.rewrite()          # al cargar el bot: completa campos y regenera names/pages
        self.db_file = db_file
        os.makedirs(os.path.dirname(db_file) or ".", exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_file, timeout=10)
        db.execute("PRAGMA foreign_keys=ON")
        return db

    # ---------------- escritura ----------------
    def set_status(self, user_id: int, character_uuid: int, dupes: int) -> None:
        """``dupes`` 0..6 para guardar, o LOCKED para quitarlo. Solo esto renueva la fecha."""
        now = int(time.time())
        with closing(self._connect()) as db, db:
            if dupes == LOCKED:
                db.execute("DELETE FROM owned WHERE user_id=? AND character=?", (user_id, character_uuid))
                left = db.execute("SELECT 1 FROM owned WHERE user_id=? LIMIT 1", (user_id,)).fetchone()
                if left:
                    db.execute("UPDATE users SET updated_at=? WHERE user_id=?", (now, user_id))
                else:
                    db.execute("DELETE FROM users WHERE user_id=?", (user_id,))
                return
            db.execute(
                "INSERT INTO users(user_id, updated_at) VALUES(?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET updated_at=excluded.updated_at", (user_id, now))
            db.execute(
                "INSERT INTO owned(user_id, character, dupes) VALUES(?, ?, ?) "
                "ON CONFLICT(user_id, character) DO UPDATE SET dupes=excluded.dupes",
                (user_id, character_uuid, max(0, min(MAX_DUPES, int(dupes)))))

    def prune(self, now: Optional[int] = None) -> int:
        """Borra los perfiles sin cambios en ``INACTIVE_DAYS``. Devuelve cuantos."""
        limit = int(now or time.time()) - INACTIVE_DAYS * 86400
        with closing(self._connect()) as db:
            with db:
                removed = db.execute("DELETE FROM users WHERE updated_at < ?", (limit,)).rowcount
            if removed:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("VACUUM")
        return removed

    # ---------------- lectura ----------------
    def owned(self, user_id: int) -> Dict[int, int]:
        """{uuid: dupes} de un usuario, tal cual esta guardado."""
        with closing(self._connect()) as db:
            return dict(db.execute("SELECT character, dupes FROM owned WHERE user_id=?", (user_id,)).fetchall())

    def get(self, user_id: int) -> Tuple[List[Tuple[dict, int]], Optional[int]]:
        """([(personaje, dupes)] de mas a menos dupes, fecha del ultimo cambio o None)."""
        self.roster.reload_if_changed()
        with closing(self._connect()) as db:
            rows = db.execute("SELECT character, dupes FROM owned WHERE user_id=?", (user_id,)).fetchall()
            last = db.execute("SELECT updated_at FROM users WHERE user_id=?", (user_id,)).fetchone()
        pairs = [(self.roster.by_uuid[c], d) for c, d in rows if c in self.roster.by_uuid]
        pairs.sort(key=lambda p: (-p[1], p[0]["name"].lower()))
        return pairs, (last[0] if last else None)
    
    def updated_at(self, user_id: int) -> Optional[int]:
        """Fecha (timestamp) del último cambio del perfil, o None si no tiene datos."""
        with closing(self._connect()) as db:
            row = db.execute("SELECT updated_at FROM users WHERE user_id=?", (user_id,)).fetchone()
        return row[0] if row else None
