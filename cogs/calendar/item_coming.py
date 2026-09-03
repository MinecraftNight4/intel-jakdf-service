# cogs/calendar/soon.py
from discord import ui
from .helpers import (
    format_ts, get_upcoming_events, get_best_roadmap_image
)
from .base import add_navigation_buttons


def panelbuilder_coming(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x03fcfc)

    container.add_item(ui.TextDisplay("## __UPCOMING CONTENT__"))

    img = get_best_roadmap_image()
    if img:
        gallery = ui.MediaGallery()
        gallery.add_item(media=img)
        container.add_item(gallery)
    else:
        container.add_item(ui.TextDisplay(
            "## __PEACE HAS RETURNED, THANKS TO EVERYONE!__\n"
            "Remember to keep up with your training and check the holiday schedule for your assigned division.\n"
            "- JAKDF"
        ))

    container.add_item(ui.Separator())

    upcoming = get_upcoming_events(3)
    if upcoming:
        lines = []
        for ts, text in upcoming:
            fmt = "R" if relative else "f"
            lines.append(f"<t:{ts}:{fmt}>:\n{text}")
        container.add_item(ui.TextDisplay("\n".join(lines)))
    else:
        container.add_item(ui.TextDisplay("*No upcoming events found.*"))

    container.add_item(ui.Separator())

    add_navigation_buttons(container, current="coming", relative=relative)
    view.add_item(container)
    return view