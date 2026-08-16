from web_get.request_news import KaijuReadNews

def run_news_scan() -> bool:
    """
    Ejecuta el scraper de noticias.
    Devuelve True si se completó correctamente, False si hubo error.
    """
    try:
        print("📰 [NEWS] Iniciando escaneo de noticias...")
        processor = KaijuReadNews()
        processor.scan_index(batch_size=3)
        processor.storage_data_news()
        print("✅ [NEWS] Escaneo de noticias completado.")
        return True
    except Exception as e:
        print(f"❌ [NEWS] Error durante el escaneo: {e}")
        return False