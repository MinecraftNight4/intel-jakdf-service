"""
Infraestructura compartida por TODOS los feeds (noticias, tienda y x.com).

Cada feed solo se encarga de decidir *qué* mandar (filtrar, ordenar, armar el
mensaje). Esta capa se encarga de *cómo* mandarlo:

    destinos  → __setup.targets(namespace)         (varios canales por guild)
    historial → load_history / commit_history       (hashes ya enviados)
    envío     → deliver()                           (canales en paralelo,
                                                     mensajes en orden dentro
                                                     de cada canal)
"""
import asyncio
import hashlib
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from logger import log

# ============================================================
# AJUSTES
#
# Discord NO fija una pausa por mensaje: los límites son dinámicos y por ruta,
# y discord.py ya espera/reintenta cuando recibe un 429. Estas pausas son
# solo cortesía para no saturar un canal.
# ============================================================
DATA_FILE = "sys_save/feed/system_data.json"

SEND_DELAY = 1.0            # s entre mensajes dentro de un mismo canal
CROSSPOST_DELAY = 2.0       # s antes de publicar (crosspost) un mensaje
SEND_TIMEOUT = 20.0         # s máximo por envío
CROSSPOST_TIMEOUT = 5.0
MAX_PARALLEL_TARGETS = 5    # canales procesándose a la vez (cada canal va en orden)
MAX_PARALLEL_DOWNLOADS = 5  # imágenes descargándose a la vez al preparar mensajes


# ============================================================
# JSON
# ============================================================
def load_json(path: str, default=None):
    if default is None:
        default = {}
    if not os.path.exists(path):
        return default.copy() if isinstance(default, (dict, list)) else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default.copy() if isinstance(default, (dict, list)) else default


def save_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)  # escritura atómica


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ============================================================
# HISTORIAL DE ENVIADOS (feed_system_data.json → {namespace: [hashes]})
#
# Una sola lista por tipo de feed: un artículo se considera "enviado" cuando
# el ciclo termina, aunque algún canal haya fallado (no se reintenta).
# ============================================================
def load_history(namespace: str) -> List[str]:
    data = load_json(DATA_FILE, {})
    raw = data.get(namespace) if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []
    return [h for h in raw if isinstance(h, str) and h]


def _dedupe(hashes: Iterable[Any]) -> List[str]:
    seen = set()
    out: List[str] = []
    for h in hashes:
        if isinstance(h, str) and h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def commit_history(
    namespace: str,
    previous: List[str],
    current: List[str],
    keep: int,
    replace: bool,
) -> None:
    """
    Guarda el historial de `namespace`.

    replace=True  (nada que enviar / nadie suscrito): queda solo lo que sigue
                  en el catálogo, para que las ofertas/artículos que
                  desaparecen no se acumulen para siempre. Además evita que un
                  canal recién configurado reciba todo el pasado.
    replace=False (tras enviar): primero lo anterior que ya no está en el
                  catálogo y al final lo actual, recortado por el principio a
                  `keep` entradas. Así el recorte solo descarta lo obsoleto y
                  nunca algo que sigue vigente (si lo vigente quedara delante,
                  cada cambio de hash haría "caducar" un hash vigente y se
                  reenviaría uno por ciclo).
    """
    current_clean = _dedupe(current)
    if replace:
        merged = current_clean
    else:
        alive = set(current_clean)
        stale = [h for h in _dedupe(previous) if h not in alive]
        merged = stale + current_clean
        if keep >= 0 and len(merged) > keep:
            merged = merged[-keep:] if keep > 0 else []

    # Se relee el archivo para tocar solo este namespace (no pisar a otros feeds).
    data = load_json(DATA_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data[namespace] = merged
    save_json(DATA_FILE, data)


# ============================================================
# IMÁGENES
# ============================================================
@dataclass(frozen=True)
class Image:
    data: bytes
    name: str


async def fetch_image(url: Optional[str], prefix: str = "feed_logo") -> Optional[Image]:
    """Descarga una imagen UNA vez (se reutiliza para todos los canales)."""
    if not url or not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    try:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()
    except Exception as e:
        log(f"[ATTACHMENT]: Error downloading [{url}] due to: {e} ", "feed", level="CRIT", show=False)
        return None

    ext = url.split("?")[0].split(".")[-1].lower()
    if ext not in ("png", "jpg", "jpeg", "gif", "webp"):
        ext = "png"
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return Image(data=data, name=f"{prefix}_{digest}.{ext}")


def dominant_colour(image: Optional[Image]) -> Optional[int]:
    """Color dominante como entero RGB, o None si no se pudo calcular."""
    if image is None:
        return None
    try:
        from colorthief import ColorThief

        r, g, b = ColorThief(io.BytesIO(image.data)).get_color(quality=1)
        return (r << 16) + (g << 8) + b
    except Exception:
        return None


# ============================================================
# ENVÍO
# ============================================================
@dataclass
class Message:
    """Un mensaje listo para mandar a cualquier canal."""
    uid: str                         # hash / id, para los logs
    label: str                       # nombre legible, para los logs
    make: Callable[[], dict]         # kwargs NUEVOS para channel.send (view/files/content)


async def resolve_channel(bot, channel_id) -> Optional[Any]:
    try:
        channel_id = int(channel_id)
    except (TypeError, ValueError):
        log(f"- [ID: {channel_id}] [FAILURE: invalid id]", "feed", level="CRIT", show=False)
        return None

    channel = bot.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await bot.fetch_channel(channel_id)
    except Exception as e:
        log(f"- [ID: {channel_id}] [FAILURE: {e}]", "feed", level="CRIT", show=False)
        return None


async def _deliver_to_target(
    bot,
    tag: str,
    target: dict,
    messages: List[Message],
    on_attempt: Callable[[], None],
) -> int:
    channel_id = target.get("channel")
    channel = await resolve_channel(bot, channel_id)
    if channel is None:
        for _ in messages:
            on_attempt()
        return 0

    is_news = bool(getattr(channel, "is_news", lambda: False)())
    do_publish = bool(target.get("publish", False))
    log(f"- [ID: {channel_id}] | [IS_NEWS: {is_news}] | [PUBLISH: {do_publish}]", "feed", show=False)

    sent = 0
    for msg in messages:
        await asyncio.sleep(SEND_DELAY)
        try:
            sent_msg = await asyncio.wait_for(channel.send(**msg.make()), timeout=SEND_TIMEOUT)
            sent += 1
            log(f"  - [SEND: SUCCESS] [ID: {channel_id}] | {msg.uid} | {msg.label}", "feed", show=False)
        except Exception as e:
            log(f"  - [(!) FAILURE] #SEND | [ID: {channel_id}] {msg.uid} - {msg.label} | DUMP: {e}", "feed", level="CRIT", show=False)
            on_attempt()
            continue

        if is_news and do_publish:
            await asyncio.sleep(CROSSPOST_DELAY)
            try:
                await asyncio.wait_for(sent_msg.publish(), timeout=CROSSPOST_TIMEOUT)
                log("        ⤷ CROSSPOST: SUCCESS", "feed", show=False)
            except Exception as e:
                log(f"        ⤷ [(!) FAILURE] #CROSSPOST | {msg.uid} - {msg.label} | DUMP: {e}", "feed", level="CRIT", show=False)
        on_attempt()

    # El ping solo tiene sentido si realmente se publicó algo en ese canal.
    ping = target.get("text")
    if sent and ping and str(ping).strip():
        await asyncio.sleep(SEND_DELAY)
        try:
            await asyncio.wait_for(channel.send(content=str(ping).strip()), timeout=SEND_TIMEOUT)
            log("    ⤷ PING: SUCCESS", "feed", show=False)
        except Exception as e:
            log(f"    ⤷ [(!) FAILURE] #PING | [ID: {channel_id}] DUMP: {e}", "feed", level="CRIT", show=False)

    return sent


async def deliver(
    bot,
    tag: str,
    targets: Dict[str, dict],
    messages: List[Message],
    progress=None,
    progress_key: Optional[str] = None,
) -> int:
    """
    Manda `messages` (en ese orden) a cada destino.

    - Los canales se procesan en paralelo (hasta MAX_PARALLEL_TARGETS);
      dentro de cada canal los mensajes salen siempre en orden.
    - Un canal que falla no afecta a los demás.
    - Devuelve cuántos mensajes se enviaron en total.
    """
    total_work = len(messages) * max(len(targets), 1)
    done = 0
    if progress and progress_key and total_work > 0:
        progress.update_progress(progress_key, 0, total_work)

    def on_attempt() -> None:
        nonlocal done
        done += 1
        if progress and progress_key:
            progress.update_progress(progress_key, done, total_work)

    log(f"[FEED - {tag}]: SENDING {len(messages)} MESSAGE(S) TO {len(targets)} CHANNEL(S)...", "feed", show=False)

    gate = asyncio.Semaphore(MAX_PARALLEL_TARGETS)

    async def run(target: dict) -> int:
        async with gate:
            try:
                return await _deliver_to_target(bot, tag, target, messages, on_attempt)
            except Exception as e:  # nunca dejar que un canal tumbe el ciclo
                log(f"[FEED - {tag}]: TARGET CRASH [ID: {target.get('channel')}] | {e}", "feed", level="CRIT", show=False)
                return 0

    results = await asyncio.gather(*(run(t) for t in targets.values()))
    return sum(results)
