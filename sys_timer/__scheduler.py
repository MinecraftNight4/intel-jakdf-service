import threading
import time
from datetime import datetime

from .news_schedule import run_news_scan
_rebuild_cache_callback = None


def set_rebuild_callback(callback):
    """Permite al bot registrar la función que reconstruye la caché."""
    global _rebuild_cache_callback
    _rebuild_cache_callback = callback
    print("✅ [TIMER] Callback de rebuild_cache registrado.")


def _should_run_now() -> bool:
    """True solo en los minutos 0 y 30."""
    return datetime.now().minute in (0, 30)


def _news_loop():
    """Loop principal del timer de noticias."""
    last_run_minute = -1

    while True:
        now = datetime.now()
        current_minute = now.minute

        # Solo ejecuta una vez por minuto válido (0 o 30)
        if current_minute in (0, 30) and current_minute != last_run_minute:
            last_run_minute = current_minute
            success = run_news_scan()

            if success and _rebuild_cache_callback is not None:
                try:
                    print("🔄 [TIMER] Reconstruyendo caché de embeds de noticias...")
                    _rebuild_cache_callback()
                    print("✅ [TIMER] Caché de embeds reconstruida.")
                except Exception as e:
                    print(f"❌ [TIMER] Error al reconstruir caché: {e}")

        # Dormir ~20 segundos para no saturar CPU y detectar el minuto a tiempo
        time.sleep(20)


def start_all_timers():
    """
    Inicia TODO lo que esté dentro de /timer/.
    Actualmente solo el timer de noticias, pero puedes agregar más threads aquí.
    """
    print("🚀 [TIMER] Iniciando todos los timers...")

    news_thread = threading.Thread(target=_news_loop, name="NewsTimer", daemon=True)
    news_thread.start()
    print("✅ [TIMER] Timer de noticias iniciado (cada hora :00 y :30).")

    # Aquí puedes agregar más timers en el futuro:
    # other_thread = threading.Thread(...)
    # other_thread.start()