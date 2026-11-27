import re
from typing import Any, Dict, List


def _extract_units(text: str) -> List[str]:
    found: List[str] = []
    pattern = r"(\[[^\]]+\]\s*[A-Za-z0-9\s\-']+?)(?:\s*\(Optimal|\s*$|\n)"
    for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
        name = re.sub(r"\s+", " ", match.group(1).strip())
        if 5 < len(name) < 80 and name not in found:
            found.append(name)
    return found


def _extract_gears(text: str) -> List[str]:
    found: List[str] = []
    pattern = r"((?:HM|SH|AR|GS|Lc|SW|Ax|RF|AW|GG|SB|Fs|T|S|PS|HG|SG)[-‐][A-Za-z0-9\- ]+?)(?=\s*[\|\(\[]|$|\n)"
    for match in re.finditer(pattern, text):
        name = match.group(1).strip()
        if name not in found:
            found.append(name)
    return found


def _extract_ranges(text: str) -> List[tuple[int, int]]:
    ranges: List[tuple[int, int]] = []
    for start_s, end_s in re.findall(r"<t:(\d+)>\s*-\s*<t:(\d+)>", text):
        start, end = int(start_s), int(end_s)
        if end > start:
            ranges.append((start, end))
    return ranges


def build_gacha_metadata(article: dict) -> Dict[str, Any]:
    """
    Construye:
    {"metadata": {"banner": UNIX|None, "event": UNIX|None, "store": UNIX|None, "unit": [], "gear": []}}
    """
    items = article.get("article_item") or []
    full_text = "\n".join(str(x) for x in items)
    lower_text = full_text.lower()

    banner_end: int | None = None
    event_end: int | None = None
    store_end: int | None = None

    ranges = _extract_ranges(full_text)
    has_shop = "exchange period" in lower_text
    has_event = "event" in lower_text and not has_shop

    if ranges:
        # Primer rango: siempre la disponibilidad del gacha/banner
        banner_end = ranges[0][1]

        if len(ranges) >= 2:
            second_end = ranges[1][1]
            if has_shop:
                store_end = second_end
            elif has_event:
                # Si el segundo rango termina antes que el banner, es el evento; si no, el banner es el mayor
                if second_end < banner_end:
                    event_end = second_end
                else:
                    event_end = banner_end
                    banner_end = second_end
            else:
                store_end = second_end

    # Respaldo usando article_unix ordenado si no hubo rangos explícitos <t:a> - <t:b>
    if banner_end is None:
        unix_list = sorted({int(u) for u in (article.get("article_unix") or []) if u})
        if len(unix_list) >= 3:
            if has_shop:
                banner_end, store_end = unix_list[1], unix_list[2]
            else:
                event_end, banner_end = unix_list[1], unix_list[2]
        elif len(unix_list) == 2:
            banner_end = unix_list[1]

    return {
        "metadata": {
            "banner": banner_end,
            "event": event_end,
            "store": store_end,
            "unit": _extract_units(full_text),
            "gear": _extract_gears(full_text),
        }
    }