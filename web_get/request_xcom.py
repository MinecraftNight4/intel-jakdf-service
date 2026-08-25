from logger import info, warn, crit, log
import requests
import json
import os
import time
import hashlib
import re


class KaijuReadXCom:
    def __init__(self, storage_file: str = "sys_save/request_xcom.json"):
        self.storage_file = storage_file
        self.xcom_storage: dict = {}

        self.accounts: list[str] = [
            "Kj8_TheGame_en",
            "kaijuno8_o_en",
            "Kj8_TheGame",
            "kaijuno8_o"
            # Añade más cuentas aquí
        ]

        self.headers = {
            "User-Agent": "kaijuno8_feed_testing | Discord: @mnight4"
        }

    # --------------------------------------------------
    # Cargar datos existentes (para no borrar roadmap)
    # --------------------------------------------------
    def load_existing(self) -> dict:
        if not os.path.exists(self.storage_file):
            return {}
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    # --------------------------------------------------
    # Guardar
    # --------------------------------------------------
    def storage_data_xcom(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(self.xcom_storage, f, ensure_ascii=False, indent=4)

            total = sum(len(acc.get("STATUS", {})) for acc in self.xcom_storage.values())
            log(f"DATABASE: [x{total} status] SUCCESS!", "xcom", show=False)
        except Exception as e:
            log(f"DATABASE: FAILURE! | {e}", "xcom", level="CRIT", show=False)

    # --------------------------------------------------
    # Texto simple (sin markdown complejo)
    # --------------------------------------------------
    def get_text(self, post: dict) -> str:
        # Preferir el texto ya limpio de la API
        text = post.get("text") or ""
        if text.strip():
            return text.strip()

        raw = post.get("raw_text") or {}
        return (raw.get("text") or "").strip()

    # --------------------------------------------------
    # Imagen más nítida del post
    # --------------------------------------------------
    def get_best_image(self, post: dict) -> str | None:
        media = (post.get("media") or {}).get("all") or []
        best_url = None
        best_area = 0

        for item in media:
            if (item.get("type") or "").lower() not in ("photo", "image"):
                continue
            url = item.get("url")
            if not url:
                continue
            w = item.get("width") or 0
            h = item.get("height") or 0
            area = w * h
            if area >= best_area:
                best_area = area
                best_url = url

        return best_url

    # --------------------------------------------------
    # Procesar un post
    # --------------------------------------------------
    def process_post(self, account: str, post: dict) -> None:
        uuid = str(post.get("id") or "")
        if not uuid:
            return

        url = post.get("url") or f"https://x.com/i/status/{uuid}"
        text = self.get_text(post)

        # Hash simple: UUID + TEXT
        raw_hash = f"{uuid}{text}"
        post_hash = hashlib.sha256(raw_hash.encode("utf-8")).hexdigest()

        # ---- STATUS ----
        if "status" not in self.xcom_storage[account]:
            self.xcom_storage[account]["status"] = {}

        self.xcom_storage[account]["status"][uuid] = {
            "link": url,
            "hash": post_hash,
            "uuid": uuid,
            "text": text,
        }

        # ---- roadmap (solo si menciona "content schedule") ----
        if "content schedule" in text.lower():
            preview = self.get_best_image(post)
            if preview:
                if "roadmap" not in self.xcom_storage[account]:
                    self.xcom_storage[account]["roadmap"] = {}

                # Solo añadir si no existe ya
                if uuid not in self.xcom_storage[account]["roadmap"]:
                    self.xcom_storage[account]["roadmap"][uuid] = {
                        "source": url,
                        "preview": preview,
                        "date": post.get("created_timestamp") or 0,
                    }
                    log(f"[roadmap] Nuevo item: {uuid}", "xcom", show=False)

    # --------------------------------------------------
    # Fetch de una cuenta
    # --------------------------------------------------
    def fetch_account(self, account: str) -> bool:
        url = f"https://api.fxtwitter.com/2/profile/{account.lower()}/statuses?count=20"
        log(f"[ACCOUNT @{account}]: [REQUEST] {url}", "xcom", show=False)

        try:
            response = requests.get(url, headers=self.headers, timeout=30)
            log(
                f"[ACCOUNT @{account.upper()}]: [STATUS {response.status_code}] [TIME {response.elapsed}]",
                "xcom",
                show=False,
            )
            response.raise_for_status()
            
            data = response.json()
            if data.get("code") != 200:
                log(f"[ACCOUNT @{account.upper()}]: API code != 200", "xcom", level="WARN", show=False)
                return False

            # Asegurar estructura de la cuenta
            if account not in self.xcom_storage:
                self.xcom_storage[account.lower()] = {"status": {}, "roadmap": {}}

            # STATUS se reemplaza cada scan (solo los posts actuales)
            self.xcom_storage[account.lower()]["status"] = {}

            results = data.get("results") or []
            for post in results:
                if post.get("type") == "status":
                    self.process_post(account.lower(), post)

            log(f"[ACCOUNT @{account.upper()}]: [SUCCESS] {len(results)} posts", "xcom", show=False)
            return True

        except Exception as e:
            log(f"[ACCOUNT @{account.upper()}]: [FAILURE] {e}", "xcom", level="CRIT", show=False)
            return False

    # --------------------------------------------------
    # Main
    # --------------------------------------------------
    def run(self) -> None:
        log("XCOM: Starting fetch...", "xcom", show=False)

        # Cargar datos existentes para preservar roadmap
        existing = self.load_existing()
        self.xcom_storage = existing

        for i, account in enumerate(self.accounts):
            # Preservar roadmap anterior de esta cuenta
            old_roadmap = {}
            if account.lower() in self.xcom_storage:
                old_roadmap = self.xcom_storage[account.lower()].get("roadmap") or {}

            self.fetch_account(account.lower())

            # Restaurar / fusionar roadmap (solo añadir, nunca borrar)
            if account.lower() not in self.xcom_storage:
                self.xcom_storage[account.lower()] = {"status": {}, "roadmap": {}}

            current_roadmap = self.xcom_storage[account.lower()].get("roadmap") or {}
            # old + new (new tiene prioridad si mismo uuid)
            merged = {**old_roadmap, **current_roadmap}
            self.xcom_storage[account.lower()]["roadmap"] = merged

            if i < len(self.accounts) - 1:
                time.sleep(5)

        self.storage_data_xcom()
        log("XCOM: Finished.", "xcom", show=False)


if __name__ == "__main__":
    processor = KaijuReadXCom()
    processor.run()