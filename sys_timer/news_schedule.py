from web_get.request_news import KaijuReadNews
from logger import info, warn, crit, log

def run_news_scan() -> bool:
    log(f"", "news", show=False)
    try:
        log(f"STATUS: Reading...", "news", show=False)
        processor = KaijuReadNews()
        processor.scan_index(batch_size=3)
        
        log(f"STATUS: Saving...", "news", show=False)
        processor.storage_data_news()
        
        log(f"STATUS: Task finished!", "news", show=False)
        return True
    except Exception as e:
        log(f"STATUS: Something went wrong: {e}", "news", level="CRIT", show=False)
        return False