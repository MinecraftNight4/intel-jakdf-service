import asyncio
import io
import math
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import discord
from discord import ui
from discord.ext import commands
from logger import log

from . import __setup as feed_setup
from .__feed import (
    MAX_PARALLEL_DOWNLOADS,
    Image,
    Message,
    as_int,
    commit_history,
    deliver,
    dominant_colour,
    fetch_image,
    load_history,
    load_json,
)

# -------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------
FEED_ITEMS_PER_PAGE = 4
NEWS_FILE = "sys_save/http/news.json"

_NEWS_LINK = "https://info.kj8-thegame.com/news/{uuid}?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8"


# -------------------------------------------------
# GENERADORES DE EMBED
# -------------------------------------------------
def _article_colour(article: dict, item_rgb: Optional[int]) -> int:
    if item_rgb is not None:
        return item_rgb
    return int(article.get("article_rgbs", "ffffff"), 16)


class FeedNewsPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        item_max: int = FEED_ITEMS_PER_PAGE,
        item_ico: str | None = None,
        item_rgb: int | None = None,
    ):
        super().__init__()

        # VARIABLE SETUP
        article_uuid = article["article_uuid"]
        article_node = article.get("article_node", [])
        article_item = article.get("article_item", [])
        article_rgbs = _article_colour(article, item_rgb)
        article_logo = item_ico or article.get("article_logo")

        math_item = len(article_node)
        math_page = max(1, math.ceil(math_item / item_max))

        page_item = article_item[:item_max]
        page_node = article_node[:item_max]

        # EMBED
        container = ui.Container(accent_colour=article_rgbs)

        # EMBED - HEADER
        if article_logo:
            gallery = ui.MediaGallery()
            gallery.add_item(media=article_logo)
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(
            f"# __{article['article_name']}__\n [`🔗`]({_NEWS_LINK.format(uuid=article_uuid)}) Posted on <t:{article['article_time']}>."
        ))
        container.add_item(ui.Separator())

        # EMBED - NEWS BODY
        text_storage: list[str] = []

        def flush_text():
            if text_storage:
                cleaned = [t.strip() for t in text_storage if t.strip()]
                if cleaned:
                    container.add_item(ui.TextDisplay("\n".join(cleaned)))
                text_storage.clear()

        for item_type, item_read in zip(page_node, page_item):
            if item_type == "txt":
                text_storage.append(item_read)
            elif item_type == "img":
                flush_text()
                gal = ui.MediaGallery()
                gal.add_item(media=item_read)
                container.add_item(gal)
            else:
                # HOW, HOOOW!?
                text_storage.append(f"**{item_type}**\n{item_read}")
        flush_text()
        container.add_item(ui.Separator())

        # EMBED - BUTTONS
        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="private_gamenews_menu"
        ))
        row.add_item(ui.Button(
            emoji="◀️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{article_uuid}_0",
            disabled=True
        ))
        row.add_item(ui.Button(
            label=f"PAGE 1 OF {math_page}",
            style=discord.ButtonStyle.success,
            custom_id=f"private_gamenews_{article_uuid}_index_1",
            disabled=1 >= math_page
        ))
        row.add_item(ui.Button(
            emoji="▶️",
            style=discord.ButtonStyle.secondary,
            custom_id=f"private_gamenews_{article_uuid}_2",
            disabled=1 >= math_page
        ))
        container.add_item(row)
        self.add_item(container)


class FeedGachaPageView(ui.LayoutView):
    def __init__(
        self,
        article: dict,
        item_rgb: int | None,
        item_txt: str,
        item_ico: str | None = None,
    ):
        super().__init__()

        # VARIABLE SETUP
        article_uuid = article["article_uuid"]
        article_rgbs = _article_colour(article, item_rgb)
        article_logo = item_ico or article.get("article_logo")

        # EMBED
        container = ui.Container(accent_colour=article_rgbs)

        # EMBED - HEADER
        if article_logo:
            gallery = ui.MediaGallery()
            gallery.add_item(media=article_logo)
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(
            f"# __{article['article_name']}__\n [`🔗`]({_NEWS_LINK.format(uuid=article_uuid)}) Posted on <t:{article['article_time']}>."
        ))
        container.add_item(ui.Separator())

        # EMBED - BODY
        container.add_item(ui.TextDisplay(item_txt))
        container.add_item(ui.Separator())

        # EMBED - BUTTONS
        row = ui.ActionRow()
        row.add_item(ui.Button(
            label="≡ MENU",
            style=discord.ButtonStyle.danger,
            custom_id="private_gamenews_menu"
        ))
        row.add_item(ui.Button(
            label="READ MORE",
            emoji="ℹ️",
            style=discord.ButtonStyle.green,
            custom_id=f"private_gamenews_{article_uuid}_1"
        ))
        container.add_item(row)
        self.add_item(container)


# -------------------------------------------------
# Gacha: determinar el texto de fechas según criterios A / B / C
# -------------------------------------------------
def build_gacha_info_text(article: dict) -> Optional[str]:
    """
    Intenta interpretar si la noticia indexada es
    valida con alguna plantilla de noticia.
    """
    # ARTICLE - VALUE CHECK
    article_item = article.get("article_item") or []
    article_unix = article.get("article_unix") or []
    article_text = "\n".join(str(i) for i in article_item).lower()
    try:
        rule_unix = sorted(int(unix) for unix in article_unix if unix is not None)
        rule_pull = "__availability period__" in article_text
        rule_shop = "exchange period" in article_text
    except (ValueError, TypeError):
        return None

    # ARTICLE TYPE FILTER:
    # GACHA PULL | EXCHANGE + AVAILABILITY + 3 UNIX
    if rule_pull and rule_shop and len(rule_unix) == 3:
        time_1, time_2, time_3 = rule_unix
        return (
            f"- [REPLACE_RELEASE] <t:{time_1}:f> (<t:{time_1}:R>)\n"
            f"- [REPLACE_GACHA_LEAVE] <t:{time_2}:f> (<t:{time_2}:R>)\n"
            f"- [REPLACE_STORE_LEAVE] <t:{time_3}:f> (<t:{time_3}:R>)"
        )

    # EVENT PULL | !EXCHANGE + AVAILABILITY + 3 UNIX
    if rule_pull and not rule_shop and len(rule_unix) == 3:
        time_1, time_2, time_3 = rule_unix
        return (
            f"- [REPLACE_RELEASE] <t:{time_1}:f> (<t:{time_1}:R>)\n"
            f"- [REPLACE_EVENT_LEAVE] <t:{time_2}:f> (<t:{time_2}:R>)\n"
            f"- [REPLACE_GACHA_LEAVE] <t:{time_3}:f> (<t:{time_3}:R>)"
        )

    # SPECIAL EVENT | !EXCHANGE + AVAILABILITY + 2 UNIX
    if rule_pull and not rule_shop and len(rule_unix) == 2:
        time_1, time_2 = rule_unix
        return (
            f"- [REPLACE_RELEASE] <t:{time_1}:f> (<t:{time_1}:R>)\n"
            f"- [REPLACE_GACHA_LEAVE] <t:{time_2}:f> (<t:{time_2}:R>)"
        )

    # NOT COMPATIBLE WITH CONTENT
    return None


# -------------------------------------------------
# DESCRIPCIÓN DE CADA FEED
#
# Para agregar un feed de noticias nuevo basta con sumar un NewsFeedSpec a
# NEWS_FEEDS (y su tipo a FEED_TYPES en cogs/feeds.py).
# -------------------------------------------------
def _attachment(image: Optional[Image]):
    """(files, url_del_adjunto) frescos: un discord.File no se puede reusar."""
    if image is None:
        return None, None
    file = discord.File(io.BytesIO(image.data), filename=image.name)
    return [file], f"attachment://{image.name}"


def _make_page_message(article: dict, image: Optional[Image], colour: Optional[int]) -> Message:
    def make() -> dict:
        files, icon = _attachment(image)
        view = FeedNewsPageView(article, item_ico=icon, item_rgb=colour, item_max=FEED_ITEMS_PER_PAGE)
        return {"view": view, "files": files}

    return Message(uid=article.get("article_hash", ""), label=article.get("article_name", ""), make=make)


def _make_gacha_message(article: dict, image: Optional[Image], colour: Optional[int], text: str) -> Message:
    def make() -> dict:
        files, icon = _attachment(image)
        view = FeedGachaPageView(article, item_rgb=colour, item_txt=text, item_ico=icon)
        return {"view": view, "files": files}

    return Message(uid=article.get("article_hash", ""), label=article.get("article_name", ""), make=make)


@dataclass(frozen=True)
class NewsFeedSpec:
    namespace: str                          # clave en __setup y en feed_system_data.json
    tag: str                                # etiqueta para los logs
    accepts: Callable[[dict], bool]         # ¿este artículo pertenece al feed?
    dominant_colour: bool = False           # usar el color dominante del logo
    gacha_layout: bool = False              # layout de gacha (fechas + READ MORE)
    eta: int = 40                           # segundos estimados (panel de progreso)


def _of_type(*types: str) -> Callable[[dict], bool]:
    wanted = {t.lower() for t in types}
    return lambda article: (article.get("article_type") or "").lower() in wanted


NEWS_FEEDS: Dict[str, NewsFeedSpec] = {
    "general": NewsFeedSpec("feed_game_general", "GENERAL", accepts=lambda a: True, eta=50),
    "service": NewsFeedSpec("feed_game_service", "SERVICE", accepts=_of_type("update", "maintenance"), eta=50),
    "gacha":   NewsFeedSpec("feed_game_gacha",   "GACHA",   accepts=_of_type("gacha"), dominant_colour=True, gacha_layout=True, eta=35),
    "event":   NewsFeedSpec("feed_game_event",   "EVENT",   accepts=_of_type("event"), dominant_colour=True, eta=35),
}


# -------------------------------------------------
# LÓGICA PRINCIPAL
# -------------------------------------------------
async def _prepare(article: dict, spec: NewsFeedSpec) -> Optional[Message]:
    """Arma el mensaje de un artículo UNA vez (imagen, color, texto)."""
    gacha_text = None
    if spec.gacha_layout:
        gacha_text = build_gacha_info_text(article)
        if gacha_text is None:
            log(
                f"  - [(!) FAILURE] #TEMPLATE | #{article.get('article_hash')}] - {article.get('article_name')} | DUMP: The article doesn't fit on the templates.",
                "feed", level="CRIT", show=False,
            )
            return None

    image = await fetch_image(article.get("article_logo"))
    colour = None
    if spec.dominant_colour and image is not None:
        # ColorThief es CPU puro: en un hilo para no congelar al bot mientras calcula.
        colour = await asyncio.get_running_loop().run_in_executor(None, dominant_colour, image)

    if spec.gacha_layout:
        return _make_gacha_message(article, image, colour, gacha_text)
    return _make_page_message(article, image, colour)


async def process_news_feed(
    bot: commands.Bot,
    spec: NewsFeedSpec,
    progress=None,
    progress_key: str | None = None,
) -> int:
    storage_news: Dict[str, Any] = load_json(NEWS_FILE, {})
    targets = feed_setup.targets(spec.namespace)
    previous = load_history(spec.namespace)
    already_sent = set(previous)

    # Catálogo de este feed, sin hashes repetidos.
    catalog: Dict[str, dict] = {}
    for article in storage_news.values():
        h = article.get("article_hash")
        if h and spec.accepts(article):
            catalog[h] = article
    current = list(catalog)

    # Lo nuevo, de más viejo a más nuevo (antes salía en orden arbitrario).
    fresh = [catalog[h] for h in current if h not in already_sent]
    fresh.sort(key=lambda a: as_int(a.get("article_time")))

    log(f"[FEED - {spec.tag}]: [CHANNELS: {len(targets)}] [ARTICLES: {len(fresh)}/{len(storage_news)}]", "feed", show=False)

    # Nada que enviar o nadie suscrito: el catálogo actual queda como "ya visto".
    if not targets or not fresh:
        commit_history(spec.namespace, previous, current, keep=len(storage_news), replace=True)
        log(f"[FEED - {spec.tag}]: THREAD CLOSED.", "feed", show=False)
        log("", "feed", show=False)
        return 0

    # Las descargas de imágenes van en paralelo (acotado); gather conserva el orden.
    gate = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)

    async def prepare(article: dict) -> Optional[Message]:
        async with gate:
            return await _prepare(article, spec)

    prepared = await asyncio.gather(*(prepare(a) for a in fresh))
    messages: List[Message] = [m for m in prepared if m is not None]

    sent = await deliver(bot, spec.tag, targets, messages, progress=progress, progress_key=progress_key)

    commit_history(spec.namespace, previous, current, keep=len(storage_news), replace=False)

    log(f"[FEED - {spec.tag}]: [SENT: {sent}]", "feed", show=False)
    log(f"[FEED - {spec.tag}]: THREAD CLOSED.", "feed", show=False)
    log(" ", "feed", show=False)
    return sent
