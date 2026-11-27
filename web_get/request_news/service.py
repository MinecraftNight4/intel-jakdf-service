import re
from typing import Any, Dict


def build_service_metadata(article: dict) -> Dict[str, Any]:
    """
    Construye:
    {"metadata": {"time_down": UNIX|None, "time_back": UNIX|None, "time_post": UNIX|None}}
    """
    items = article.get("article_item") or []
    full_text = "\n".join(str(x) for x in items)
    lower_text = full_text.lower()
    art_type = (article.get("article_type") or "").lower()
    title_upper = (article.get("article_name") or "").upper()

    time_down: int | None = None
    time_back: int | None = None
    time_post: int | None = None

    # 1. Detectar ventana de mantenimiento (<t:A> - <t:B> o <t:A> 〜 <t:B>)
    maint_match = re.search(r"<t:(\d+)>\s*(?:-|〜|~)\s*<t:(\d+)>", full_text)
    if maint_match:
        t1, t2 = int(maint_match.group(1)), int(maint_match.group(2))
        if t2 > t1:
            time_down = t1
            time_back = t2

    # 2. Detectar reinicio por Data Update
    data_update_match = re.search(
        r"data update is scheduled for the following time:\s*<t:(\d+)>",
        lower_text,
    )
    if data_update_match:
        time_post = int(data_update_match.group(1))
    elif art_type == "update" and "DATA UPDATE" in title_upper and not time_down:
        unix_list = article.get("article_unix") or []
        if unix_list:
            time_post = int(unix_list[0])

    # 3. Si el anuncio ya indica explícitamente que finalizó, limpiar ventana activa
    completed_hints = (
        "the data update has been successfully completed",
        "maintenance has been completed.",
        "update is now available.",
    )
    if any(hint in lower_text for hint in completed_hints):
        time_down = None
        time_back = None
        time_post = None

    return {
        "metadata": {
            "time_down": time_down,
            "time_back": time_back,
            "time_post": time_post,
        }
    }