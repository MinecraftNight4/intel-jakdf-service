"""
Scheduler: cada 30 minutos ejecuta un ciclo de tres fases.

    FASE 1  Fetching  scrapers (sys_timer/fetchers.py)
    FASE 2  Building  reconstruye la caché de cada cog (refresh_cache)
    FASE 3  Posting   publica los feeds (sys_timer/feed/)

Los cogs y los feeds se registran desde main.py; el scheduler no los importa.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from logger import log

from . import fetchers
from .progress import ProgressDisplay

# ============================================================
# AJUSTES
# ============================================================
CYCLE_MINUTES = (0, 30)     # minutos de cada hora en que arranca un ciclo
FETCH_PARALLEL = True       # False = scrapers uno tras otro (orden clásico)


# ============================================================
# FASE 1 – definición de los scrapers
# ============================================================
@dataclass(frozen=True)
class Fetch:
    key: str                                              # clave en el panel de progreso
    label: str
    eta: int                                              # segundos estimados
    run: Callable[[ProgressDisplay, str], bool]           # (progress, key) -> ok


# Orden en que aparecen en el panel.
FETCHES: Dict[str, Fetch] = {f.key: f for f in (
    Fetch("news", "Fetching NEWS", 60, fetchers.run_news_scan),
    Fetch("xcom", "Fetching xAPI", 20, fetchers.run_xcom_scan),
    Fetch("rmap", "Fetching RMAP", 60, fetchers.run_rmap_scan),
    Fetch("sale", "Fetching SALE", 40, fetchers.run_sale_scan),
)}

# Cada cadena corre en su propio hilo y, dentro de una cadena, en orden.
# RMAP lee el JSON que escribe XCom, así que va detrás de él.
FETCH_CHAINS: Tuple[Tuple[str, ...], ...] = (
    ("sale",),
    ("news",),
    ("xcom", "rmap"),
)

# Si ninguno de estos funciona, el ciclo se aborta (RMAP no cuenta).
CRITICAL_FETCHES = ("news", "xcom", "sale")


# ============================================================
# Registros (se llenan desde main.py)
# ============================================================
class _Refresher(NamedTuple):
    key: str
    label: str
    eta: int
    func: Callable[[], None]


_refreshers: Dict[str, _Refresher] = {}
_feed_callback: Optional[Callable[[ProgressDisplay], None]] = None
_feed_tasks: List[Tuple[str, str, int]] = []      # (key, label, eta) de la fase 3


def register_refresher(name: str, func: Callable[[], None], key: str, label: str, eta: int = 10):
    """Registra (o reemplaza) la función que reconstruye la caché de un cog."""
    _refreshers[name] = _Refresher(key=key, label=label, eta=eta, func=func)
    log(f"TIMER: [REGISTER: {name}]", "timer", show=False)


def set_feed_callback(callback: Callable[[ProgressDisplay], None], tasks: List[Tuple[str, str, int]]):
    """
    callback(progress): publica todos los feeds (bloquea hasta terminar).
    tasks: [(key, label, eta)] que aparecerán en la fase 3 del panel.
    """
    global _feed_callback, _feed_tasks
    _feed_callback = callback
    _feed_tasks = list(tasks)
    log("TIMER: [REGISTER: feeds]", "timer", show=False)


# ============================================================
# Loop principal del timer
# ============================================================
def _timer_loop():
    last_slot = None

    while True:
        now = datetime.now()
        slot = (now.year, now.month, now.day, now.hour, now.minute)

        if now.minute in CYCLE_MINUTES and slot != last_slot:
            last_slot = slot
            try:
                run_full_cycle()
            except Exception as e:
                # Que un error inesperado no mate el hilo del timer.
                log(f"SCHEDULER CRASH: {type(e).__name__}: {e}", "timer", level="CRIT")

        time.sleep(20)


# ============================================================
# Ciclo completo
# ============================================================
_cycle_lock = threading.Lock()


def run_full_cycle() -> bool:
    """
    Ejecuta un ciclo. Devuelve False si no corrió porque ya había otro en
    curso (p. ej. `!runschedule` mientras el timer estaba trabajando); dos
    ciclos a la vez publicarían los mismos artículos dos veces.
    """
    if not _cycle_lock.acquire(blocking=False):
        log("SCHEDULER: a cycle is already running, skipped", "timer", level="WARN")
        return False
    try:
        _run_cycle()
        return True
    finally:
        _cycle_lock.release()


def _run_fetch(progress: ProgressDisplay, fetch: Fetch) -> bool:
    progress.start_task(fetch.key)
    try:
        ok = bool(fetch.run(progress, fetch.key))
    except Exception as e:
        log(f"FETCH ERROR [{fetch.key}]: {type(e).__name__}: {e}", "timer", level="CRIT", show=False)
        ok = False
    progress.success(fetch.key) if ok else progress.failure(fetch.key)
    return ok


def _phase_fetch(progress: ProgressDisplay) -> Dict[str, bool]:
    progress.set_phase(1)
    for fetch in FETCHES.values():
        progress.add_task(fetch.key, fetch.label, eta_seconds=fetch.eta)

    results: Dict[str, bool] = {}

    def run_chain(chain: Tuple[str, ...]):
        for key in chain:
            results[key] = _run_fetch(progress, FETCHES[key])

    if FETCH_PARALLEL and len(FETCH_CHAINS) > 1:
        with ThreadPoolExecutor(max_workers=len(FETCH_CHAINS), thread_name_prefix="fetch") as pool:
            for future in [pool.submit(run_chain, chain) for chain in FETCH_CHAINS]:
                future.result()
    else:
        for chain in FETCH_CHAINS:
            run_chain(chain)

    return results


def _phase_build(progress: ProgressDisplay) -> None:
    progress.set_phase(2)

    refreshers = list(_refreshers.values())
    for r in refreshers:
        progress.add_task(r.key, r.label, eta_seconds=r.eta)

    for r in refreshers:
        progress.start_task(r.key)
        try:
            r.func()
            progress.success(r.key)
        except Exception as e:
            progress.failure(r.key)
            log(f"REBUILD ERROR [{r.key}]: {type(e).__name__}: {e}", "timer", level="CRIT", show=False)


def _phase_post(progress: ProgressDisplay) -> None:
    if not _feed_callback:
        return

    progress.set_phase(3)
    for key, label, eta in _feed_tasks:
        progress.add_task(key, label, eta_seconds=eta)

    try:
        _feed_callback(progress)
    except Exception as e:
        log(f"FEED CALLBACK ERROR: {type(e).__name__}: {e}", "timer", level="CRIT")
        # Que lo que no llegó a ejecutarse no se quede en "Waiting..." como si nada.
        for key, _label, _eta in _feed_tasks:
            if progress.tasks.get(key, {}).get("status") in ("waiting", "running"):
                progress.failure(key)


def _run_cycle() -> None:
    started = time.time()
    progress = ProgressDisplay()
    progress.start()

    aborted = False
    try:
        results = _phase_fetch(progress)

        # Si la fase 1 falló por completo → abortar
        if any(results.get(key) for key in CRITICAL_FETCHES):
            _phase_build(progress)
            _phase_post(progress)
        else:
            aborted = True
    finally:
        progress.stop()

    # El log va DESPUÉS de stop(): stop() limpia el panel y borraría la línea.
    if aborted:
        log("========[SCHEDULER ABORTED - Phase 1 failed]========", "timer")
    else:
        log(f"========[SCHEDULER COMPLETE | {time.time() - started:.0f}s]========", "timer")


# ============================================================
# Arranque
# ============================================================
def start_all_timers():
    log("TIMER: LOADING...", "bots", show=False)
    thread = threading.Thread(target=_timer_loop, name="SchedulerTimer", daemon=True)
    thread.start()
    log("TIMER: Timers loaded!", "bots", show=False)
