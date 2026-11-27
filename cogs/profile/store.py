# cogs/profile/store.py
"""Datos de /profile. Sin dependencias de discord, para poder probarlo solo.

- Roster (lista de personajes): ``sys_save/profile/roster.json``, se edita a mano.
  El ``uuid`` es lo que se guarda por usuario: se puede renombrar un personaje o cambiar su
  icono sin perder datos. Los cambios al archivo se detectan solos (sin reiniciar el bot).
- Perfiles de usuarios: UN texto por usuario (``codec.pack``), no una fila por personaje.
    * Copia local (SQLite, ``sys_save/profile/profile.db``): de ahi lee el bot siempre.
    * Base remota (Turso, opcional): la comparte la Activity. Se escribe en diferido, ver ``ProfileStore``.
  Los perfiles sin cambios durante ``INACTIVE_DAYS`` se borran (``prune``).
"""
import asyncio
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Dict, List, Optional, Tuple

from . import codec
from .codec import MAX_DUPES
from .remote import RemoteError, TursoRemote

ROSTER_FILE = "sys_save/profile/roster.json"
DB_FILE = "sys_save/profile/profile.db"

LOCKED = -1                 # "estado" para quitar el personaje (bloqueado)
INACTIVE_DAYS = 365

# --- ahorro de lecturas/escrituras en la base remota ---
QUIET_SECONDS = 60          # un perfil se envia cuando lleva este tiempo sin cambios...
MAX_WAIT_SECONDS = 600      # ...o, aunque lo sigan tocando, a mas tardar a los 10 min
CACHE_TTL = 900             # tras 15 min se vuelve a leer de la nube (por si la Activity lo cambio)
CACHE_KEEP_DAYS = 14        # copias locales sin uso (y ya enviadas) se descartan tras 2 semanas

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    user_id     INTEGER PRIMARY KEY,
    data        TEXT    NOT NULL,              -- codec.pack(); "" = sin personajes
    updated_at  INTEGER NOT NULL DEFAULT 0,    -- ultimo cambio REAL (0 = nunca)
    synced      TEXT,                          -- ``data`` tal como esta en la nube (NULL = no esta alli)
    fetched_at  INTEGER NOT NULL DEFAULT 0,    -- ultima vez que se confirmo con la nube
    dirty_since INTEGER NOT NULL DEFAULT 0,    -- 0 = al dia; si no, desde cuando espera envio
    touched     INTEGER NOT NULL DEFAULT 0     -- ultimo cambio local pendiente de enviar
);
CREATE INDEX IF NOT EXISTS idx_profiles_dirty ON profiles(dirty_since) WHERE dirty_since > 0;
"""


class ProfileUnavailable(Exception):
    """No hay copia local del perfil y la base remota no responde: no se puede leer ni editar sin riesgo."""


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


_COLS = "data, updated_at, synced, fetched_at, dirty_since, touched"
_UPSERT_LOCAL = (
    "INSERT INTO profiles(user_id, data, updated_at, synced, fetched_at, dirty_since, touched) "
    "VALUES(?, ?, ?, NULL, ?, ?, ?) "
    "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, "
    "touched=excluded.touched, "
    "dirty_since=CASE WHEN profiles.dirty_since=0 THEN excluded.dirty_since ELSE profiles.dirty_since END"
)


class ProfileStore:
    """Perfiles de usuarios con copia local y base remota opcional (Turso).

    Como se ahorran lecturas y escrituras en la nube:
      * UNA fila por usuario (``codec.pack``), no una por personaje: guardar el perfil entero = 1 fila.
      * El bot lee siempre de la copia local. A la nube solo va a buscar un perfil que no tiene
        (1 lectura) o cuya copia tiene mas de ``CACHE_TTL`` segundos (se refresca sin bloquear).
      * Las ediciones se guardan al instante en local y se envian en diferido (``flush``): un perfil
        sale cuando lleva ``QUIET_SECONDS`` sin cambios (o ``MAX_WAIT_SECONDS`` como tope). Cien clics
        en el panel de edicion = una sola escritura.
      * Si al enviar el perfil queda igual que en la nube (el usuario deshizo sus cambios), no se escribe.
      * Todos los perfiles pendientes de un ``flush`` viajan en una sola transaccion.
      * Si la nube falla, nada se pierde: queda pendiente en local y se reintenta en el siguiente ``flush``.

    Sin base remota (``remote=None``) todo funciona igual pero solo en local.
    """

    def __init__(self, roster_file: str = ROSTER_FILE, db_file: str = DB_FILE, remote="env", clock=time.time):
        self.roster = Roster(roster_file)
        self.roster.rewrite()          # al cargar el bot: completa campos y regenera names/pages
        self.db_file = db_file
        self.clock = clock
        self.remote = TursoRemote.from_env() if remote == "env" else remote
        self._refreshing = set()
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_file) or ".", exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                db.executescript(_SCHEMA)
                self.legacy_imported = self._import_legacy(db)
                if self.remote:
                    # perfiles creados antes de tener nube: se envian una vez
                    db.execute("UPDATE profiles SET dirty_since=1, touched=1 "
                               "WHERE synced IS NULL AND data != '' AND dirty_since=0")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_file, timeout=10)

    def _import_legacy(self, db: sqlite3.Connection) -> int:
        """Pasa las tablas viejas (``users`` + ``owned``, una fila por personaje) al formato nuevo.

        Las tablas viejas se renombran a ``legacy_*`` (queda una copia de seguridad que se puede borrar).
        """
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "owned"} <= tables:
            return 0
        now = int(self.clock())
        queued = 1 if self.remote else 0
        owned: Dict[int, Dict[int, int]] = {}
        for user_id, character, dupes in db.execute("SELECT user_id, character, dupes FROM owned"):
            owned.setdefault(user_id, {})[character] = dupes
        count = 0
        for user_id, updated_at in db.execute("SELECT user_id, updated_at FROM users").fetchall():
            data = codec.pack(owned.get(user_id, {}))
            if data:
                db.execute(
                    "INSERT OR IGNORE INTO profiles(user_id, data, updated_at, synced, fetched_at, dirty_since, touched) "
                    "VALUES(?, ?, ?, NULL, ?, ?, ?)", (user_id, data, updated_at, now, queued, queued))
                count += 1
        db.execute("DROP TABLE IF EXISTS legacy_owned")
        db.execute("DROP TABLE IF EXISTS legacy_users")
        db.execute("ALTER TABLE owned RENAME TO legacy_owned")
        db.execute("ALTER TABLE users RENAME TO legacy_users")
        return count

    # ---------------- copia local y nube ----------------
    @staticmethod
    def _local_row(db: sqlite3.Connection, user_id: int):
        return db.execute(f"SELECT {_COLS} FROM profiles WHERE user_id=?", (user_id,)).fetchone()

    def _fetch(self, user_id: int) -> None:
        """Lee el perfil de la nube (1 fila) y lo guarda en local, salvo que haya cambios sin enviar."""
        found = self.remote.get(user_id)
        data, updated_at = found if found else ("", 0)
        with closing(self._connect()) as db, db:
            db.execute(
                "INSERT INTO profiles(user_id, data, updated_at, synced, fetched_at) VALUES(?, ?, ?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at, "
                "synced=excluded.synced, fetched_at=excluded.fetched_at WHERE profiles.dirty_since=0",
                (user_id, data, updated_at, data if found else None, int(self.clock())))

    def _backoff(self, user_id: int) -> None:
        """La nube fallo: no volver a intentarlo en cada lectura, sino en un minuto."""
        with closing(self._connect()) as db, db:
            db.execute("UPDATE profiles SET fetched_at=? WHERE user_id=? AND dirty_since=0",
                       (int(self.clock()) - CACHE_TTL + 60, user_id))

    def _refresh_later(self, user_id: int) -> None:
        with self._lock:
            if user_id in self._refreshing:
                return
            self._refreshing.add(user_id)

        def work():
            try:
                self._fetch(user_id)
            except Exception:
                self._backoff(user_id)
            finally:
                with self._lock:
                    self._refreshing.discard(user_id)

        threading.Thread(target=work, daemon=True).start()

    def _row(self, user_id: int, wait: bool):
        """Fila local del usuario (o None). Consulta la nube solo si no hay copia o esta caducada.

        ``wait=False`` (lecturas desde los paneles): una copia caducada se devuelve tal cual y se
        refresca en segundo plano. Sin copia no hay mas remedio que esperar a la nube.
        """
        with closing(self._connect()) as db:
            row = self._local_row(db, user_id)
        if self.remote is None:
            return row
        missing = row is None
        stale = not missing and row[4] == 0 and int(self.clock()) - row[3] > CACHE_TTL
        if not (missing or stale):
            return row
        if not (missing or wait):
            self._refresh_later(user_id)
            return row
        try:
            self._fetch(user_id)
        except RemoteError as err:
            if missing:
                raise ProfileUnavailable(str(err)) from err
            self._backoff(user_id)
            return row
        with closing(self._connect()) as db:
            return self._local_row(db, user_id)

    async def load(self, user_id: int) -> None:
        """Trae el perfil a la copia local sin bloquear el bot. Llamarlo antes de leerlo en un comando.

        Lanza ``ProfileUnavailable`` si no hay copia local y la nube no responde.
        """
        await asyncio.to_thread(self._row, user_id, True)

    # ---------------- escritura ----------------
    def set_status(self, user_id: int, character_uuid: int, dupes: int) -> None:
        """``dupes`` 0..6 para guardar, o LOCKED para quitarlo. Solo un cambio real renueva la fecha."""
        row = self._row(user_id, wait=False)
        owned = codec.unpack(row[0]) if row else {}
        before = dict(owned)
        if dupes == LOCKED:
            owned.pop(character_uuid, None)
        else:
            owned[character_uuid] = max(0, min(MAX_DUPES, int(dupes)))
        if owned == before:
            return
        now = int(self.clock())
        queued = now if self.remote else 0
        with closing(self._connect()) as db, db:
            db.execute(_UPSERT_LOCAL, (user_id, codec.pack(owned), now, now, queued, queued))

    def flush(self, force: bool = False) -> int:
        """Envia a la nube los perfiles pendientes que ya llevan su tiempo sin cambios (o todos con ``force``).

        Devuelve cuantas filas se escribieron. Lanza ``RemoteError`` si la nube falla (todo queda pendiente).
        """
        if self.remote is None:
            return 0
        now = int(self.clock())
        with closing(self._connect()) as db:
            rows = db.execute(
                "SELECT user_id, data, updated_at, synced, touched FROM profiles "
                "WHERE dirty_since > 0 AND (? OR touched <= ? OR dirty_since <= ?)",
                (1 if force else 0, now - QUIET_SECONDS, now - MAX_WAIT_SECONDS)).fetchall()
        upserts, deletes, same = [], [], []
        for user_id, data, updated_at, synced, touched in rows:
            if data == (synced or ""):
                same.append((user_id, data, touched))
            elif data == "":
                deletes.append((user_id, touched))
            else:
                upserts.append((user_id, data, updated_at, touched))
        if not rows:
            return 0
        self.remote.apply([(u, d, t) for u, d, t, _ in upserts], [u for u, _ in deletes])
        with closing(self._connect()) as db, db:
            for user_id, data, _, touched in upserts:
                db.execute("UPDATE profiles SET synced=?, fetched_at=?, dirty_since=0 "
                           "WHERE user_id=? AND data=? AND touched=?", (data, now, user_id, data, touched))
            for user_id, touched in deletes:
                db.execute("UPDATE profiles SET synced=NULL, fetched_at=?, dirty_since=0 "
                           "WHERE user_id=? AND data='' AND touched=?", (now, user_id, touched))
            for user_id, data, touched in same:
                db.execute("UPDATE profiles SET dirty_since=0 WHERE user_id=? AND data=? AND touched=?",
                           (user_id, data, touched))
        return len(upserts) + len(deletes)

    def pending(self) -> int:
        """Cuantos perfiles esperan ser enviados a la nube."""
        with closing(self._connect()) as db:
            return db.execute("SELECT COUNT(*) FROM profiles WHERE dirty_since > 0").fetchone()[0]

    def prune(self, now: Optional[int] = None) -> int:
        """Borra los perfiles sin cambios en ``INACTIVE_DAYS`` (nube y copia local). Devuelve cuantos.

        Es una sola sentencia en la nube. La copia local tambien descarta lo que lleva
        ``CACHE_KEEP_DAYS`` sin usarse (si hay nube: ahi sigue el original).
        """
        now = int(now or self.clock())
        limit = now - INACTIVE_DAYS * 86400
        remote_removed = self.remote.delete_older(limit) if self.remote else 0
        with closing(self._connect()) as db:
            with db:
                local = db.execute("DELETE FROM profiles WHERE dirty_since=0 AND updated_at > 0 AND updated_at < ?",
                                   (limit,)).rowcount
                if self.remote:
                    db.execute("DELETE FROM profiles WHERE dirty_since=0 AND fetched_at < ?",
                               (now - CACHE_KEEP_DAYS * 86400,))
            if local:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("VACUUM")
        return remote_removed or local

    # ---------------- lectura ----------------
    def owned(self, user_id: int) -> Dict[int, int]:
        """{uuid: dupes} de un usuario, tal cual esta guardado."""
        row = self._row(user_id, wait=False)
        return codec.unpack(row[0]) if row else {}

    def get(self, user_id: int) -> Tuple[List[Tuple[dict, int]], Optional[int]]:
        """([(personaje, dupes)] de mas a menos dupes, fecha del ultimo cambio o None)."""
        self.roster.reload_if_changed()
        row = self._row(user_id, wait=False)
        owned = codec.unpack(row[0]) if row else {}
        pairs = [(self.roster.by_uuid[c], d) for c, d in owned.items() if c in self.roster.by_uuid]
        pairs.sort(key=lambda p: (-p[1], p[0]["name"].lower()))
        return pairs, (row[1] if row and row[0] and row[1] else None)

    def updated_at(self, user_id: int) -> Optional[int]:
        """Fecha (timestamp) del último cambio del perfil, o None si no tiene datos."""
        row = self._row(user_id, wait=False)
        return row[1] if row and row[0] and row[1] else None
