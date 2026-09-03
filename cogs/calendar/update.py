# cogs/calendar/update.py
from discord import ui
from .helpers import load_json, now_unix, format_ts, NEWS_FILE
from .base import add_navigation_buttons

def build_update_view(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    news = load_json(NEWS_FILE, {})
    now = now_unix()

    candidate = None
    for art in news.values():
        t = (art.get("article_type") or "").lower()
        if t not in ("update", "maintenance"):
            continue
        unixes = art.get("article_unix") or []
        if not unixes:
            continue
        # Solo consideramos mantenimientos que aún no han terminado
        if max(unixes) > now:
            candidate = art
            break

    if candidate is None:
        # No hay mantenimiento activo → mensaje neutral
        container = ui.Container(accent_colour=0x546e7a)
        container.add_item(ui.TextDisplay(
            "## __NO ACTIVE MAINTENANCE__\nEverything is running normally."
        ))
        container.add_item(ui.Separator())
    else:
        name = (candidate.get("article_name") or "UPDATE").upper()
        unixes = candidate.get("article_unix") or [0, 0]
        u1 = unixes[0]
        u2 = unixes[1] if len(unixes) > 1 else u1

        is_data_update = "DATA UPDATE" in name
        in_progress = u1 <= now < u2

        if is_data_update:
            accent = 0x11d6d0
            title = f"## __{name}__\n### 📥 __DATA UPDATE NOTICE!__ 📥"
            body = (
                f"> All players will be kicked to home screen "
                f"{'at ' if not relative else ''}{format_ts(u1, relative, 'f')} "
                f"to download the update data."
            )
        elif in_progress:
            accent = 0xfc2803
            title = f"## __{name}__\n### 🔴 __MAINTENANCE IN PROGRESS!!__ 🚫"
            body = (
                f"> This maintenance started "
                f"{'on ' if not relative else ''}{format_ts(u1, relative, 'f')}.\n\n"
                f"### 🟢 **END OF MAINTENANCE**\n"
                f"> If everything runs as planned, **service will be restored "
                f"{'on ' if not relative else ''}{format_ts(u2, relative, 'f')}**."
            )
        else:
            accent = 0xfcd703
            title = f"## __{name}__\n### 🔴 __MAINTENANCE NOTICE!__ 🚫"
            body = (
                f"> The game will be offline "
                f"{'on ' if not relative else ''}{format_ts(u1, relative, 'f')} "
                f"for maintenance and will kick any logged player at that moment.\n\n"
                f"🟢 **END OF MAINTENANCE**\n"
                f"> Services will be restored "
                f"{'on ' if not relative else ''}{format_ts(u2, relative, 'f')}, "
                f"allowing users to download new data and log in."
            )

        container = ui.Container(accent_colour=accent)
        if candidate.get("article_logo"):
            gallery = ui.MediaGallery()
            gallery.add_item(media=candidate["article_logo"])
            container.add_item(gallery)
        container.add_item(ui.TextDisplay(title))
        container.add_item(ui.TextDisplay(body))
        container.add_item(ui.Separator())

    add_navigation_buttons(container, current="update", relative=relative)
    view.add_item(container)
    return view