import threading
import time
from datetime import datetime

from .news_schedule import run_news_scan

# Callbacks que el bot registrará
_rebuild_cache_callback = None
_feed_callback = None


def set_rebuild_callback(callback):
    global _rebuild_cache_callback
    _rebuild_cache_callback = callback
    print("✅ [TIMER] Callback de rebuild_cache registrado.")


def set_feed_callback(callback):
    global _feed_callback
    _feed_callback = callback
    print("✅ [TIMER] Callback de feeds registrado.")


def _should_run_now() -> bool:
    return datetime.now().minute in (0, 30)


def _news_loop():
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        # Solo ejecuta una vez por minuto válido (0 o 30)
        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            success = run_news_scan()

            # 1. Reconstruir caché de embeds
            if success and _rebuild_cache_callback is not None:
                try:
                    print("🔄 [TIMER] Reconstruyendo caché de embeds de noticias...")
                    _rebuild_cache_callback()
                    print("✅ [TIMER] Caché de embeds reconstruida.")
                except Exception as e:
                    print(f"❌ [TIMER] Error al reconstruir caché: {e}")

            # 2. Procesar feeds (después de la caché)
            if success and _feed_callback is not None:
                try:
                    print("📡 [TIMER] Procesando feeds...")
                    _feed_callback()
                    print("✅ [TIMER] Feeds procesados.")
                except Exception as e:
                    print(f"❌ [TIMER] Error en feeds: {e}")

        # Dormir ~20 segundos para no saturar CPU y detectar el minuto a tiempo
        time.sleep(20)


def start_all_timers():
    print("🚀 [TIMER] Iniciando todos los timers...")

    news_thread = threading.Thread(target=_news_loop, name="NewsTimer", daemon=True)
    news_thread.start()
    print("✅ [TIMER] Timer de noticias iniciado (cada hora :00 y :30).")
