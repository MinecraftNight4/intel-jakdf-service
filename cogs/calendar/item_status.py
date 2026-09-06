# cogs/calendar/update.py
import re
from discord import ui
from .helpers import (
    fetchjson, now_as_unix, format_time_view, NEWS_FILE,
    status_show_display, format_full_text
)
from .base import add_navigation_buttons


def panelbuilder_status(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    news = fetchjson(NEWS_FILE, {})
    now = now_as_unix()

    #===================#
    # CANDIDATE FILTER
    #===================#
    candidate_data = None
    candidate_time = 0

    for art in news.values():
        if art.get("article_type") in ("update", "maintenance"):
            art_time = art.get("article_time", 0)
            if art_time > candidate_time:
                candidate_name = art.get("article_name")
                candidate_time = art_time
                candidate_data = art
    
    #================#
    # CALENDAR EMPTY #
    #================#
    if not candidate_data:
        rgbs = 0x546e7a
        text = "## __WELP... THIS IS EMPTY... `≡(▔﹏▔)≡`__"

    #==================#
    # CALENDAR BUILDER #
    #==================#
    if candidate_data:
        #                   
        #   CONTENT FILTER
        #                   
        display_unix_open = 0
        display_unix_ends = 0
        candidate_text = format_full_text(candidate_data)
        candidate_unix = candidate_data.get("article_unix") or []
        
        
        for i, unix in enumerate(candidate_unix):
            # MAINTENANCE
            if i + 1 < len(candidate_unix):
                temp_unix_next = candidate_unix[i + 1]
                (f"<t:{unix}> - <t:{temp_unix_next}>") in candidate_text
                display_unix_open = unix
                display_unix_ends = temp_unix_next
                break
            # DATA UPDATE
            if (f"a data update is scheduled for the following time:\n<t:{unix}>") in candidate_text:
                display_unix_ends = unix
        
        
        #                   
        #   DATA DISPLAY
        #                   
        if "DATA UPDATE" in candidate_data.get("article_name"):
            rgbs = 0x11d6d0
            text = f"## 📥__{candidate_name}__ 📥 \n## > 📨 __DATA UPDATE!__ 📨 \n- Everyone will be forced to update {'at ' if not relative else ''}{format_time_view(display_unix_ends, relative, 'f')}"

        elif display_unix_open != 0:
            rgbs = 0xfcd703
            text = f"## ⚠️ __{candidate_name}__ ⚠️ \n## > ℹ️ __MAINTENANCE SCHEDULE!__ ℹ️ \n- The maintenance operations will start {'at ' if not relative else ''}{format_time_view(display_unix_open, relative, 'f')}. \n- Service should be restored {'at ' if not relative else ''}{format_time_view(display_unix_ends, relative, 'f')}."

        elif display_unix_open <= now:
            rgbs = 0xfc2803
            text = f"## 🚧 __{candidate_name}__ 🚧 \n## > 🔴 __SERVERS OFFLINE!__ 🔴 \n- The maintenance operations started {'at ' if not relative else ''}{format_time_view(display_unix_open, relative, 'f')} \n \n## > 🟢 __ETA OF THE MAINTENANCE__ 🟢\n- Service is expected to be restored {'on ' if not relative else ''}{format_time_view(display_unix_ends, relative, 'f')}"
        
    #                   
    #   EMBED BUILDER
    #                   
    container = ui.Container(accent_colour=rgbs)
    if candidate_data.get("article_logo"):
        gallery = ui.MediaGallery()
        gallery.add_item(media=candidate_data["article_logo"])
        container.add_item(gallery)
        
    container.add_item(ui.TextDisplay(text))
    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="status", relative=relative)
    view.add_item(container)
    return view
    