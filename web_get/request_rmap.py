import os
import json
import time
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from logger import log

load_dotenv()

# ============================================================
# CONFIGURACIÓN
# ============================================================
XCOM_FILE = "sys_save/request_xcom.json"
RMAP_FILE = "sys_save/request_rmap.json"

MODELS = [
    "gemini-3.6-flash",
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.7-flash",
]

MAX_RETRIES = 3
RETRY_DELAY = 4

client = genai.Client(api_key=os.getenv("GEMINITOKEN"))


# ============================================================
# PROMPT
# ============================================================
SYSTEM_PROMPT = """
You are an expert at reading game content schedule / roadmap images from Kaiju No. 8 THE GAME.

Analyze the provided image carefully and extract EVERY event/schedule item visible.

Return ONLY a valid JSON array. No markdown, no explanations, no extra text.

Each object must have exactly these fields:
- "event_name": string (full clean name of the event)
- "type": string (one of: GACHA, STORY EVENT, EVENT, CAMPAIGN, LOGIN BONUS, MAINTENANCE, CHARACTER, WEAPON, or similar short uppercase category)
- "date_jst": string in format "YYYY-MM-DD HH:MM JST" (if only date is shown, use 12:00)
- "timestamp": integer (Unix timestamp in seconds for that JST time)

Rules:
- Convert all times correctly from JST (UTC+9) to Unix timestamp.
- If a time is not specified, assume 12:00 JST.
- Events like "Login Bonus" and "2x Training" starts at 04:00 JST.
- Be as accurate as possible with names.
- Ignore decorative text, hashtags, and non-event information.
- Sort the events by timestamp ascending.
"""


# ============================================================
# UTILIDADES
# ============================================================
def load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def download_image_bytes(url: str) -> bytes:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def build_format(listed: list) -> dict:
    grouped = {}
    for item in listed:
        ts = str(item["timestamp"])
        line = f"- `{item['type']}` {item['event_name']}"
        if ts not in grouped:
            grouped[ts] = line
        else:
            grouped[ts] += f"\n{line}"
    return grouped


# ============================================================
# LIMPIEZA DE ROADMAPS EXPIRADOS
# ============================================================
def cleanup_expired_roadmaps(xcom: dict, rmap: dict) -> tuple[dict, dict]:
    now = int(time.time())
    removed = 0

    log(f"ROADMAP CLEANER:", "rmap", level="WARN", show=False)
    for account, account_data in list(xcom.items()):
        log(f"[@{account.upper()}]", "rmap", show=False)
        roadmap = account_data.get("roadmap", {})

        for post_id in list(roadmap.keys()):
            post_id = str(post_id)

            # Solo evaluamos los que ya fueron procesados
            if "ends_at" not in roadmap[post_id]:
                continue

            rmap_entry = rmap.get(post_id)
            if not rmap_entry:
                continue

            listed = rmap_entry.get("listed", [])
            if not listed:
                continue

            # Obtenemos el timestamp más alto del roadmap
            max_ts = max(item.get("timestamp", 0) for item in listed)

            # Si el último evento ya pasó → eliminar
            if max_ts < now:
                # Borrar de xcom
                del xcom[account]["roadmap"][post_id]

                # Borrar de rmap
                if post_id in rmap:
                    del rmap[post_id]

                removed += 1
                log(f"  - [DELETED: {post_id}] [EXPIRED AT: {max_ts}]", "rmap", level="WARN", show=False)
            else:
                log(f"  - [SKIPPED: {post_id}] [EXPIRES AT: {max_ts}]", "rmap", show=False)

    if removed > 0:
        log(f"[DELETED: {removed}]", "rmap", show=False)
        log(f" ", "rmap", show=False)

    return xcom, rmap


# ============================================================
# LLAMADA A GEMINI CON REINTENTOS + FALLBACK
# ============================================================
def ask_gemini(image_bytes: bytes, handshake: str) -> list | None:
    log(f"ROADMAP SCAN FOR: {handshake}", "gemini-api", show=False)
    last_error = None

    for model in MODELS:
        log(f"[MODEL: {model}]: ", "gemini-api", show=False)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Part.from_bytes(
                            data=image_bytes,
                            mime_type="image/jpeg"
                        ),
                        SYSTEM_PROMPT
                    ],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1,
                    )
                )

                data = json.loads(response.text)

                if isinstance(data, list) and len(data) > 0:
                    log(f"  - [STATUS: SUCCESS] [ATTEMPT: {attempt}/{MAX_RETRIES}] [JSON: TRUE]", "gemini-api", show=False)
                    return data

                log(f"  - [STATUS: SUCCESS] [ATTEMPT: {attempt}/{MAX_RETRIES}] [JSON: FALSE]", "gemini-api", show=False)
                return []

            except Exception as e:
                last_error = str(e)
                error_str = last_error.lower()

                if "503" in error_str or "unavailable" in error_str or "high demand" in error_str:
                    wait = RETRY_DELAY * attempt
                    log(f"  - [STATUS: FAILURE] [ATTEMPT: {attempt}/{MAX_RETRIES}] [REPORT: OVERLOAD! - Waiting {wait}s...]", "gemini-api", level="WARN", show=False)
                    time.sleep(wait)
                    continue
                
                log(f"  - [STATUS: FAILURE] [ATTEMPT: {attempt}/{MAX_RETRIES}] [REPORT: {e}]", "gemini-api", level="WARN", show=False)
                break

    log(f"  - [STATUS: FAILURE] [ATTEMPTS: FALSE] [REPORT: {last_error}]", "gemini-api", level="CRIT", CRITlevel="CRIT")
    return None


# ============================================================
# PROCESO PRINCIPAL
# ============================================================
def process_roadmaps():
    xcom = load_json(XCOM_FILE)
    rmap = load_json(RMAP_FILE)

    if not xcom:
        log(f"DATABASE: THE DATABASE IS EMPTY!", "rmap", level="WARN", show=False)
        return

    # 1. Primero limpiamos los que ya expiraron
    xcom, rmap = cleanup_expired_roadmaps(xcom, rmap)

    processed = 0
    failed = 0

    for account, account_data in xcom.items():
        log(f"- ACCOUNT: @{account.upper()}:", "rmap", show=False)
        roadmap = account_data.get("roadmap", {})
        for post_id, entry in list(roadmap.items()):
            post_id = str(post_id)
            log(f"  - {post_id}", "rmap", show=False)

            # Solo procesar los que NO tengan ends_at
            if "ends_at" in entry:
                log(f"    - SKIPPED", "rmap", show=False)
                continue

            preview = entry.get("preview")
            source = entry.get("source", "")

            if not preview:
                log(f"    - FAILURE! | This roadmap doesn't contains an attachment!?", "rmap", level="WARN", show=False)
                continue
            
            log(f"    - READING...", "rmap", level="WARN", show=False)
            try:
                image_bytes = download_image_bytes(preview)
                handshake = source
                events = ask_gemini(image_bytes, handshake)

                if events is None:
                    failed += 1
                    continue

                if not events:
                    log(f"    - STATUS: No event entries available to index!", "rmap", level="WARN", show=False)
                    continue

                # Éxito real
                rmap[post_id] = {
                    "listed": events,
                    "format": build_format(events),
                    "display": preview,
                    "source": source,
                    "account": account,
                    "processed_at": int(time.time())
                }

                entry["ends_at"] = int(time.time())
                processed += 1
                log(f"    - [EVENTS: {len(events)}]", "rmap", show=False)

                time.sleep(4.0)

            except Exception as e:
                log(f"    - FAILURE | {e}", "rmap", level="CRIT", show=False)
                failed += 1
        log(f" ~~~ ", "rmap", show=False)

    # Guardar cambios
    save_json(RMAP_FILE, rmap)
    save_json(XCOM_FILE, xcom)
    log(f"[SCHEDULES READED: {processed}] | [FAILURES: {failed}]", "rmap", show=False)
    log(f" ", "rmap", show=False)


def run_rmap_scan() -> bool:
    try:
        process_roadmaps()
        return True
    except Exception as e:
        log(f"FAILURE | {e}", "rmap", show=False)
        return False


if __name__ == "__main__":
    run_rmap_scan()