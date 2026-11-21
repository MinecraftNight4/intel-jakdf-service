"""
Fase 1 del scheduler: los scrapers.

Antes eran cuatro archivos casi idénticos (news/xcom/sale/rmap _schedule.py);
ahora comparten un único envoltorio que registra el resultado en el log de
cada fuente y devuelve True/False.

Todos aceptan (progress, key) aunque no lo usen, para que el scheduler los
llame igual.
"""
from typing import Callable, Optional

from logger import log
from web_get.request_news import KaijuReadNews
from web_get.request_rmap import run_rmap_scan as _rmap_job
from web_get.request_sale import run_sale_scan as _sale_job
from web_get.request_xcom import KaijuReadXCom


def _scan(tag: str, name: str, job: Callable[[], Optional[bool]]) -> bool:
    """Ejecuta `job` registrando inicio/fin en sys_save/logs/<día>/<tag>.log."""
    log("", tag, show=False)
    try:
        log(f"OUTSIDE PROTOCOL: Reading {name}...", tag, show=False)
        result = job()
        log("OUTSIDE PROTOCOL: CLOSED!", tag, show=False)
        return True if result is None else bool(result)
    except Exception as e:
        log(f"OUTSIDE PROTOCOL: FAILURE | {e}", tag, level="CRIT", show=False)
        return False


def run_news_scan(progress=None, key=None) -> bool:
    def job():
        processor = KaijuReadNews()
        processor.scan_index(batch_size=3)
        log("OUTSIDE PROTOCOL: Saving...", "news", show=False)
        processor.storage_data_news()

    return _scan("news", "News", job)


def run_xcom_scan(progress=None, key: str = "xcom") -> bool:
    def job():
        KaijuReadXCom().run(progress=progress, progress_key=key)

    return _scan("xcom", "XCom", job)


def run_sale_scan(progress=None, key=None) -> bool:
    return _scan("sale", "Store", _sale_job)


def run_rmap_scan(progress=None, key=None) -> bool:
    # Lee lo que guarda XCom: debe correr DESPUÉS de run_xcom_scan.
    return _scan("rmap", "Roadmaps", _rmap_job)
