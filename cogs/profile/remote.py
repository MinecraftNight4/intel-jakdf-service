# cogs/profile/remote.py
"""Base de datos remota (Turso). Una fila por usuario: ``profiles(user_id, data, updated_at)``.

Variables de entorno (en el ``.env`` del bot; nunca en el codigo):
    TURSO_DATABASE_URL   ``libsql://nombre-usuario.turso.io``
    TURSO_AUTH_TOKEN     token con permiso de escritura (el de solo lectura es para la web)
    TURSO_DRIVER         opcional: ``libsql`` (por defecto) o ``turso_serverless``

Sin ``TURSO_DATABASE_URL`` el bot funciona solo con la base local.

Cada operacion abre su propia conexion y la cierra: asi no hay conexiones ociosas que caduquen, y
no se comparte nada entre hilos (los drivers no documentan seguridad entre hilos).
"""
import os
from contextlib import closing
from typing import Iterable, List, Optional, Tuple

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS profiles ("
    " user_id INTEGER PRIMARY KEY,"
    " data TEXT NOT NULL,"
    " updated_at INTEGER NOT NULL)",
    "CREATE INDEX IF NOT EXISTS idx_profiles_updated ON profiles(updated_at)",
)

# Solo escribe si el texto cambia de verdad: un guardado repetido no cuenta como fila escrita.
UPSERT = (
    "INSERT INTO profiles(user_id, data, updated_at) VALUES(?, ?, ?) "
    "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at "
    "WHERE profiles.data != excluded.data"
)


class RemoteError(Exception):
    """La base remota no responde o rechazo la consulta (sin internet, cuota agotada, token malo...)."""


def _all(cursor) -> list:
    fetch = getattr(cursor, "fetchall", None)
    return list(fetch() if fetch else cursor)


class DbApiRemote:
    """Logica comun sobre cualquier conexion tipo DB-API; las subclases solo implementan ``_connect``."""

    def __init__(self):
        self._ready = False

    def _connect(self):
        raise NotImplementedError

    def _open(self):
        try:
            conn = self._connect()
            if not self._ready:
                for sql in SCHEMA:
                    conn.execute(sql)
                conn.commit()
                self._ready = True
            return conn
        except RemoteError:
            raise
        except Exception as err:
            raise RemoteError(f"{type(err).__name__}: {err}") from err

    def get(self, user_id: int) -> Optional[Tuple[str, int]]:
        """(data, updated_at) o None si el usuario no tiene perfil. Lee UNA fila."""
        try:
            with closing(self._open()) as conn:
                rows = _all(conn.execute("SELECT data, updated_at FROM profiles WHERE user_id=?", (user_id,)))
        except RemoteError:
            raise
        except Exception as err:
            raise RemoteError(f"{type(err).__name__}: {err}") from err
        return (str(rows[0][0]), int(rows[0][1])) if rows else None

    def apply(self, upserts: Iterable[Tuple[int, str, int]], deletes: Iterable[int]) -> None:
        """Guarda y borra perfiles en una sola transaccion."""
        upserts, deletes = list(upserts), list(deletes)
        if not (upserts or deletes):
            return
        try:
            with closing(self._open()) as conn:
                for row in upserts:
                    conn.execute(UPSERT, row)
                for user_id in deletes:
                    conn.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
                conn.commit()
        except RemoteError:
            raise
        except Exception as err:
            raise RemoteError(f"{type(err).__name__}: {err}") from err

    def delete_older(self, limit: int) -> int:
        """Borra los perfiles cuyo ultimo cambio es anterior a ``limit``. Devuelve cuantos (0 si el driver no lo dice)."""
        try:
            with closing(self._open()) as conn:
                cursor = conn.execute("DELETE FROM profiles WHERE updated_at < ?", (limit,))
                conn.commit()
                return max(0, int(getattr(cursor, "rowcount", 0) or 0))
        except RemoteError:
            raise
        except Exception as err:
            raise RemoteError(f"{type(err).__name__}: {err}") from err


class TursoRemote(DbApiRemote):
    def __init__(self, url: str, token: str, driver: Optional[str] = None):
        super().__init__()
        self.url, self.token = url, token
        self.driver = (driver or "libsql").lower()

    @classmethod
    def from_env(cls) -> Optional["TursoRemote"]:
        url = (os.getenv("TURSO_DATABASE_URL") or "").strip()
        if not url:
            return None
        return cls(url, (os.getenv("TURSO_AUTH_TOKEN") or "").strip(), os.getenv("TURSO_DRIVER"))

    def _connect(self):
        if self.driver == "turso_serverless":
            import turso_serverless
            return turso_serverless.connect(self.url, auth_token=self.token)
        import libsql
        return libsql.connect(database=self.url, auth_token=self.token)
