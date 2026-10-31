from web_get.request_xcom import KaijuReadXCom
from logger import info, warn, crit, log


def run_xcom_scan(progress=None, progress_key: str = "xcom") -> bool:
    log(f"", "xcom", show=False)
    try:
        log(f"OUTSIDE PROTOCOL: Reading XCom...", "xcom", show=False)
        processor = KaijuReadXCom()
        processor.run(progress=progress, progress_key=progress_key)
        
        log(f"OUTSIDE PROTOCOL: CLOSED!", "xcom", show=False)
        return True
    except Exception as e:
        log(f"OUTSIDE PROTOCOL: FAILURE | {e}", "xcom", level="CRIT", show=False)
        return False