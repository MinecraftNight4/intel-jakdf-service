# cogs/calendar/soon.py
from discord import ui
from .helpers import (
    format_time_view, calendar_unix_list, calendar_rmap_view
)
from .base import add_navigation_buttons


def panelbuilder_coming(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x03fcfc)

    container.add_item(ui.TextDisplay("## __UPCOMING CONTENT__"))

    img = calendar_rmap_view()
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

    upcoming = calendar_unix_list(3)
    if upcoming:
        lines = []
        lines.append("### __TRANSCRIPTION OF COMING EVENTS:__")
        for ts, text in upcoming:
            if relative:
                lines.append(f"- 🗓️ __Starts <t:{ts}:R>:__\n{text}")
            else:
                lines.append(f"- 🗓️ __Starts on <t:{ts}:f>:__\n{text}")
        container.add_item(ui.TextDisplay("\n".join(lines)))
    else:
        container.add_item(ui.TextDisplay("*No upcoming events found.*"))

    container.add_item(ui.Separator())

    add_navigation_buttons(container, current="coming", relative=relative)
    view.add_item(container)
    return view