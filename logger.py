import os
import sys
from datetime import datetime
from threading import Lock

# ============================================================
# CONFIGURACIÓN
# ============================================================
LOG_DIR = "sys_save/logs"

# Colores para consola
COLORS = {
    "INFO": "\033[92m",   # Verde
    "WARN": "\033[93m",   # Amarillo
    "CRIT": "\033[91m",   # Rojo
    "RESET": "\033[0m",
}

_lock = Lock()

def _get_log_file(prefix: str = "main") -> str:
    os.makedirs(LOG_DIR, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    prefix = "".join(c for c in prefix if c.isalnum() or c in ("_", "-")).strip() or "main"
    return os.path.join(LOG_DIR, f"{prefix}_{today}.log")


def log(message: str, prefix: str = "main", level: str = "INFO", show: bool = True):
    """
    Uso:
        log("mensaje")
        log("mensaje", "nombre_archivo")
        log("mensaje", "nombre_archivo", "WARN")
        log("mensaje", level="CRIT")
    """
    level = str(level).upper().strip()
    if level not in ("INFO", "WARN", "CRIT"):
        level = "INFO"

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {message}"

    try:
        with _lock:
            with open(_get_log_file(prefix), "a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception as e:
        print(f"[LOGGER ERROR] No se pudo escribir el log: {e}", file=sys.stderr)

    if show:
        color = COLORS.get(level, COLORS["RESET"])
        print(f"{color}{line}{COLORS['RESET']}")


# ============================================================
# ATAJOS
# ============================================================
def info(message: str, prefix: str = "main", show: bool = True):
    log(message, prefix=prefix, level="INFO", show=show)

def warn(message: str, prefix: str = "main", show: bool = True):
    log(message, prefix=prefix, level="WARN", show=show)

def crit(message: str, prefix: str = "main", show: bool = True):
    log(message, prefix=prefix, level="CRIT", show=show)