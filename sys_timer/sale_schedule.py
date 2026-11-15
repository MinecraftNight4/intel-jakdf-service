from web_get.request_sale import run_sale_scan
from logger import log


def run_sale_scan_wrapper() -> bool:
    log(f"", "sale", show=False)
    try:
        log(f"OUTSIDE PROTOCOL: Reading Store...", "sale", show=False)
        ok = run_sale_scan()
        log(f"OUTSIDE PROTOCOL: CLOSED!", "sale", show=False)
        return bool(ok)
    except Exception as e:
        log(f"OUTSIDE PROTOCOL: FAILURE | {e}", "sale", level="CRIT", show=False)
        return False