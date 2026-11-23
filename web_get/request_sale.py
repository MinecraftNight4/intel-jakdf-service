from __future__ import annotations

import hashlib
import json
import os
import re

from datetime import datetime, timedelta, timezone
from logger import log
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag


# ============================================================
# FEATURES AND RULES
# ============================================================

STORE_URL = "https://webstore.kj8-thegame.com/?language=en"
FALLBACK_BANNER = "https://asset.kj8-thegame.com/static/production/images/en/webstore_kv-c686d07bdb76271fe016dbfe3a61063e.jpg"

UTC = timezone.utc
RESET_HOUR_UTC = 19

IGNORE_HEADINGS = {"enter serial code to claim in-game items.","legal disclosures","download here","confirm","confirm purchase","error","purchase","sign in","obtainable items"}
MAINTENANCE_HINTS = ("maintenance","mantenimiento","under maintenance","temporarily unavailable","currently unavailable","メンテナンス","维护","維護")


# ============================================================
# UTILITIES
# ============================================================

def tool_timestamp() -> int:
    return int(datetime.now(UTC).timestamp())


def tool_hashupdate(sku: str, text_entry: str) -> str:
    raw = f"{sku}___{text_entry}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


_TIME_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def tool_timeleft(raw: str) -> int | None:
    """Segundos de un texto como ``8d left``, ``21h left``, ``1d 5h``, ``45m left``."""
    parts = re.findall(r"(\d+)\s*([dhms])\b", str(raw or ""), re.I)
    if not parts:
        return None
    return sum(int(n) * _TIME_UNITS[u.lower()] for n, u in parts)


def tool_timeparse(raw: str, reference: datetime | None = None) -> int | None:
    """Fecha de fin estimada a partir del tiempo restante que muestra la tienda.

    La tienda redondea hacia abajo (``8d`` = entre 8 y 9 dias) y todo termina a la hora de
    reinicio, asi que el fin es el primer reinicio a partir de ``ahora + restante``. Da el
    mismo resultado en cada ciclo mientras el texto mostrado sea coherente, sea en dias,
    horas o minutos, y no cambia cuando el texto pasa de ``1d`` a ``23h``.
    """
    if (left := tool_timeleft(raw)) is None:
        return None
    current = (reference or datetime.now(UTC)).astimezone(UTC)
    earliest = current + timedelta(seconds=left)

    reset = earliest.replace(hour=RESET_HOUR_UTC, minute=0, second=0, microsecond=0)
    if reset < earliest:
        reset += timedelta(days=1)
    return int(reset.timestamp())


def tool_textlore(node: Tag | None) -> str:
    if node is None:
        return ""

    for br in node.find_all("br"):
        br.replace_with("\n")

    text = node.get_text("", strip=False)
    text = text.replace("{;;nl;;}", "\n")
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def safe_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    return url if url.startswith(("http://", "https://")) else None


def tool_readitem(soup: BeautifulSoup) -> str:
    node = soup.select_one(".ui-kv-main")
    style = (node.get("style") if node else "") or ""
    match = re.search(r"url\(([^)]+)\)", style)
    if match:
        raw = match.group(1).strip(" \"'")
        if safe := safe_url(raw):
            return safe
    return FALLBACK_BANNER


def tool_checkstatus(soup: BeautifulSoup) -> str:
    found = []
    for el in soup.select("h1, h2, h3, h4"):
        if el.find_parent("div.ui-dialog") or el.find_parent("button"):
            continue
        text = el.get_text(" ", strip=True)
        if not text or text.lower() in IGNORE_HEADINGS or len(text) < 8:
            continue
        found.append(text)

    blob = soup.get_text(" ", strip=True).lower()
    for text in found:
        if any(hint in text.lower() for hint in MAINTENANCE_HINTS):
            return text
    if any(hint in blob for hint in MAINTENANCE_HINTS):
        return found[0] if found else "Store is under maintenance."
    return found[0] if found else "ERROR: CATEGORY IS MISSING"


def tool_pairitems(area: Tag | None) -> list[tuple[Tag, Tag | None]]:
    if area is None:
        return []
    pending = None
    pairs = []

    for el in area.find_all(recursive=False):
        classes = el.get("class") or []
        if el.name == "button" and "js-product" in classes:
            if pending is not None:
                pairs.append((pending, None))
            pending = el
        elif pending is not None and el.name == "div" and "ui-dialog" in classes:
            pairs.append((pending, el))
            pending = None
    if pending is not None:
        pairs.append((pending, None))
    return pairs


def tool_timelabel(button: Tag) -> str:
    for selector in ("p.ui-day.timer", "p.ui-day.update", "p.ui-day"):
        node = button.select_one(selector)
        if not node:
            continue
        text = node.get_text(" ", strip=True)
        if tool_timeleft(text) is not None:
            return text
    return ""


def tool_buildtext(name: str, price: str, limit: int | None, ends_at: int | None, indexed_at: int, lore: str, on_sale: bool = False) -> str:
    lines = [f"### `US${price}` {name}"]

    meta = []
    if on_sale:
        meta.append(f"📉 SALE!")
    if limit is not None:
        meta.append(f"📦 x{limit} left")
    if ends_at is not None:
        meta.append(f"⌛ Leaves on <t:{ends_at}:s>(<t:{ends_at}:R>).")
    if meta:
        lines.append("-# " + ", ".join(meta))

    lines.append(f"-# 🛃 Listed by bot <t:{indexed_at}:R>.")
    lines.append("```")
    lines.append(lore or "This is weird but... Where is the text!?!")
    lines.append("```")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Clase principal
# ─────────────────────────────────────────────────────────────

class SaleScanner:
    def __init__(self, storage_file: str = "sys_save/http/sale.json"):
        self.storage_file = storage_file
        self.storage: dict[str, Any] = self._empty()

    def _empty(self) -> dict:
        return {
            "service-last_ping": None,
            "service-last_code": None,
            "service-last_fail": None,
            "service-last_logo": FALLBACK_BANNER,
            "item_data": {},
            "pack_data": {},
            "view_data": {},
            "hash_notification": [],
        }

    def load(self) -> None:
        self.storage = self._empty()
        if not os.path.exists(self.storage_file):
            return
        try:
            with open(self.storage_file, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.storage.update(data)
        except Exception as e:
            log(f"DATABASE: LOAD FAILURE | {e}", "sale", level="CRIT", show=False)

    def save(self) -> None:
        try:
            folder = os.path.dirname(self.storage_file)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(self.storage, f, ensure_ascii=False, indent=2)
            count = len(self.storage.get("item_data") or {})
            log(f"DATABASE: [x{count} offers] SUCCESS!", "sale", show=False)
        except Exception as e:
            log(f"DATABASE: SAVE FAILURE | {e}", "sale", level="CRIT", show=False)

    def _previous_indexes(self) -> dict[str, int]:
        indexes = {}
        for sku, item in (self.storage.get("item_data") or {}).items():
            ts = item.get("time_index")
            if isinstance(ts, (int, float)):
                indexes[sku] = int(ts)
        return indexes

    def parse(self, html: str, reference: datetime | None = None) -> dict:
        html = html.replace("<br>", "{;;nl;;}").replace("<br/>", "{;;nl;;}").replace("<br />", "{;;nl;;}")
        soup = BeautifulSoup(html, "html.parser")
        labels = soup.select("div.ui-product-label")
        previous = self._previous_indexes()
        moment = reference or datetime.now(UTC)
        current_ts = int(moment.timestamp())

        item_data: dict[str, dict] = {}
        pack_data: dict[str, dict] = {}
        view_data: dict[str, list] = {}

        for idx, label in enumerate(labels, start=1):
            name_node = label.select_one("h2.ui-language-en")
            section_name = name_node.get_text(" ", strip=True) if name_node else ""

            if not section_name:
                message = tool_checkstatus(soup)
                log("ERROR: CATEGORY IS MISSING", "sale", level="WARN", show=False)
                log(f"ERROR: ATTACHED DATA: {message}", "sale", level="WARN", show=False)
                return {"ok": False, "status": "maintenance", "message": message, "http_code": 200}

            section_id = f"section_{idx}"
            area = label.find_next_sibling()
            pairs = tool_pairitems(area)

            sku_list = []
            view_list = []

            for button, dialog in pairs:
                sku = (button.get("data-sku") or "").strip()
                if not sku:
                    continue

                price = (button.get("data-product-price") or "").strip()
                name_el = button.select_one("p.ui-language-en")
                name = name_el.get_text(" ", strip=True) if name_el else "ERROR"

                icon_el = button.select_one("div.ui-content img")
                icon = safe_url(icon_el.get("src") if icon_el else None)

                stock_el = button.select_one("p.ui-product-count")
                stock_text = stock_el.get_text(" ", strip=True) if stock_el else ""
                limit = None
                if stock_text:
                    m = re.search(r"\d+", stock_text)
                    if m:
                        limit = int(m.group(0))

                timer_label = tool_timelabel(button)
                ends_at = tool_timeparse(timer_label, moment) if timer_label else None
                on_sale = "sale" in (button.get("class") or [])

                bonus_el = button.select_one(".ui-bonus-label")
                plus = bonus_el.get_text(" ", strip=True) if bonus_el else ""

                lore_el = None
                if dialog is not None:
                    lore_el = dialog.select_one("p.for-pc.for-md.ui-description-text")
                text = tool_textlore(lore_el)

                time_index = previous.get(sku, current_ts)

                text_entry = tool_buildtext(
                    name=name,
                    price=price,
                    limit=limit,
                    ends_at=ends_at,
                    indexed_at=time_index,
                    lore=text,
                    on_sale=on_sale,
                )

                item_hash = tool_hashupdate(sku, text_entry)

                item_data[sku] = {
                    "name": name,
                    "icon": icon,
                    "text": text,
                    "plus": plus,
                    "cost": price,
                    "sale": on_sale,
                    "hash": item_hash,
                    "limit": limit,
                    "time_index": time_index,
                    "time_limit": ends_at,
                    "text_entry": text_entry,
                }

                sku_list.append(sku)
                view_list.append({
                    "text": text_entry,
                    "icon": icon,
                })

            pack_data[section_id] = {
                "name": section_name.upper(),
                "list": sku_list,
            }
            view_data[section_id] = view_list

        if not pack_data:
            message = tool_checkstatus(soup)
            log("ERROR: CATEGORY IS MISSING", "sale", level="WARN", show=False)
            log(f"ERROR: ATTACHED DATA: {message}", "sale", level="WARN", show=False)
            return {"ok": False, "status": "maintenance", "message": message, "http_code": 200}

        return {
            "ok": True,
            "status": "ok",
            "banner": tool_readitem(soup),
            "item_data": item_data,
            "pack_data": pack_data,
            "view_data": view_data,
            "http_code": 200,
        }

    def apply_success(self, parsed: dict, http_code: int = 200) -> None:
        """Aplica un parseo exitoso y guarda."""
        self.storage["service-last_ping"] = tool_timestamp()
        self.storage["service-last_code"] = http_code
        self.storage["service-last_fail"] = None
        self.storage["service-last_logo"] = parsed.get("banner") or FALLBACK_BANNER
        
        self.storage["item_data"] = parsed["item_data"]
        self.storage["pack_data"] = parsed["pack_data"]
        self.storage["view_data"] = parsed["view_data"]
        self.save()

    def hold(self, status: str, http_code: int | None, message: str) -> None:
        """Mantiene el catálogo anterior y solo actualiza el estado."""
        self.storage["service-last_ping"] = tool_timestamp()
        self.storage["service-last_code"] = http_code
        self.storage["service-last_fail"] = message
        self.save()

    def scan(self, html: str | None = None, reference: datetime | None = None) -> bool:
        log("[!] START: FETCHING...", "sale", show=False)
        self.load()

        code = 200
        body = html

        if body is None:
            try:
                response = requests.get(STORE_URL, timeout=60, headers={"User-Agent": "Mozilla/5.0 (JAKDF DISCORD BOT - SCANNING UPDATES - @mnight4)"})
                code = response.status_code
                body = response.text
            except Exception as e:
                log(f"CODE: NETWORK | {e}", "sale", level="CRIT", show=False)
                self.hold("error", None, str(e))
                log("[!] END", "sale", show=True)
                return False

        if code != 200 or body is None:
            log(f"CODE: {code}", "sale", level="WARN", show=False)
            self.hold("error", code, f"CODE: {code}")
            log("[!] END", "sale", show=True)
            return False

        log(f"CODE: 200 / LENGTH: {len(body)}", "sale", show=False)
        parsed = self.parse(body, reference=reference)

        if not parsed.get("ok"):
            self.hold(parsed.get("status") or "maintenance", code, parsed.get("message") or "")
            log("[!] END", "sale", show=True)
            return False

        log(f"SECTIONS: {len(parsed['pack_data'])}", "sale", show=False)
        self.apply_success(parsed, http_code=code)
        total = len(parsed["item_data"])
        log(f"[!] END items={total}", "sale", show=True)
        return True


# ─────────────────────────────────────────────────────────────
# API pública
# ─────────────────────────────────────────────────────────────

def run_sale_scan(storage_file: str = "sys_save/http/sale.json") -> bool:
    return SaleScanner(storage_file).scan()
