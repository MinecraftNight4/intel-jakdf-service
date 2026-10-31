import sys
import time
import threading
from typing import Dict, Optional

SPINNER = ["[-]", "[/]", "[|]", "[\\]"]

class ProgressDisplay:
    def __init__(self):
        self.lock = threading.Lock()
        self.tasks: Dict[str, dict] = {}
        self.phase = 0
        self._spinner_idx = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_lines = 0
        self._started = False

    def start(self):
        self._started = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._spinner_loop, daemon=True)
        self._thread.start()
        self._render()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)

        # --- Limpieza agresiva ---
        # Subimos muchas líneas y borramos todo lo que haya hacia abajo
        clear_lines = max(self._last_lines + 40, 60)
        sys.stdout.write(f"\033[{clear_lines}A")
        sys.stdout.write("\033[J")          # borra desde el cursor hasta el final
        sys.stdout.flush()

        # Ahora imprimimos UNA sola vez el panel final limpio
        self._last_lines = 0               # para que no intente subir de nuevo
        self._render(final=True)

        # Espaciado final
        print("\n")

    def set_phase(self, phase: int):
        with self.lock:
            self.phase = phase
            self._render()

    def add_task(self, key: str, label: str, eta_seconds: int = 0):
        with self.lock:
            self.tasks[key] = {
                "label": label,
                "status": "waiting",
                "eta_seconds": eta_seconds,      # estimado inicial
                "remaining": eta_seconds,        # se actualiza dinámicamente
                "start_time": None,
                "done": 0,
                "total": 0,
                "message": ""
            }
            self._render()

    def start_task(self, key: str):
        with self.lock:
            if key in self.tasks:
                t = self.tasks[key]
                t["status"] = "running"
                t["start_time"] = time.time()
                t["remaining"] = t["eta_seconds"]
                self._render()

    def success(self, key: str, message: str = "Success"):
        with self.lock:
            if key in self.tasks:
                self.tasks[key]["status"] = "success"
                self.tasks[key]["message"] = message
                self._render()

    def failure(self, key: str, message: str = "Failure"):
        with self.lock:
            if key in self.tasks:
                self.tasks[key]["status"] = "failure"
                self.tasks[key]["message"] = message
                self._render()

    # ========== NUEVO: Actualización dinámica ==========
    def update_eta(self, key: str, remaining_seconds: int):
        """Actualiza manualmente los segundos restantes."""
        with self.lock:
            if key in self.tasks and self.tasks[key]["status"] == "running":
                self.tasks[key]["remaining"] = max(0, remaining_seconds)
                self._render()

    def update_progress(self, key: str, done: int, total: int):
        """
        Actualiza progreso real (ej: 3/10 artículos).
        Calcula ETA automáticamente según velocidad actual.
        """
        with self.lock:
            if key not in self.tasks or self.tasks[key]["status"] != "running":
                return

            t = self.tasks[key]
            t["done"] = done
            t["total"] = total

            if done > 0 and t["start_time"]:
                elapsed = time.time() - t["start_time"]
                rate = done / elapsed          # items por segundo
                remaining_items = total - done
                t["remaining"] = int(remaining_items / rate) if rate > 0 else 0
            self._render()

    # --------------------------------------------------
    def _spinner_loop(self):
        while not self._stop.is_set():
            with self.lock:
                self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER)
                # Solo decrementar ETA estimado si no hay progreso real
                for t in self.tasks.values():
                    if t["status"] == "running" and t["total"] == 0 and t["start_time"]:
                        elapsed = time.time() - t["start_time"]
                        t["remaining"] = max(0, int(t["eta_seconds"] - elapsed))
                self._render()
            time.sleep(0.18)

    def _get_icon(self, status: str) -> str:
        if status == "running":
            return SPINNER[self._spinner_idx]
        if status == "success":
            return "[✔️]"
        if status == "failure":
            return "[❌]"
        return "[O]"

    def _get_extra(self, t: dict) -> str:
        if t["status"] in ("success", "failure"):
            return f" {t['message']}"
        if t["status"] == "waiting":
            return " || Waiting..."
        # running
        if t["total"] > 0:
            return f" || {t['done']}/{t['total']} || ETA: {t['remaining']}s"
        return f" || ETA: {t['remaining']}s"

    def _build_output(self) -> list[str]:
        lines = ["-----------------------"]

        if self.phase >= 1:
            lines.append("* PHASE 1:")
            for key in ["news", "xcom"]:
                if key in self.tasks:
                    t = self.tasks[key]
                    lines.append(f"{t['label']}: {self._get_icon(t['status'])}{self._get_extra(t)}")

        if self.phase >= 2:
            lines.append("")
            lines.append("* PHASE 2:")
            for key in ["embed", "calendar", "feeds_build"]:
                if key in self.tasks:
                    t = self.tasks[key]
                    lines.append(f"{t['label']}: {self._get_icon(t['status'])}{self._get_extra(t)}")

        if self.phase >= 3:
            lines.append("")
            lines.append("* PHASE 3:")
            for key in [
                "general", "service", "gacha", "event",
                "xcom-kj8_thegame_en",
                "xcom-kaijuno8_o_en",
                "xcom-kj8_thegame",
                "xcom-kaijuno8_o"
                ]:
                if key in self.tasks:
                    t = self.tasks[key]
                    lines.append(f"{t['label']}: {self._get_icon(t['status'])}{self._get_extra(t)}")

        lines.append("-----------------------")
        return lines

    def _render(self, final: bool = False):
        if not self._started and not final:
            return

        lines = self._build_output()
        output = "\n".join(lines)

        if not final and self._last_lines > 0:
            sys.stdout.write(f"\033[{self._last_lines}A\033[J")

        sys.stdout.write(output + ("\n" if not final else ""))
        sys.stdout.flush()
        self._last_lines = len(lines)