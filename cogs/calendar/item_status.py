# cogs/calendar/update.py
from discord import ui
from .helpers import now_as_unix, format_time_view, get_active_service_notice
from .base import add_navigation_buttons


def panelbuilder_status(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    now = now_as_unix()
    candidate_data = get_active_service_notice()

    rgbs = 0x546E7A
    text = "## __WELP... THIS IS EMPTY... `≡(▔﹏▔)≡`__"

    if candidate_data:
        candidate_name = candidate_data.get("article_name") or ""
        meta = candidate_data.get("metadata") or {}
        time_down = meta.get("time_down")
        time_back = meta.get("time_back")
        time_post = meta.get("time_post")

        if time_post and int(time_post) > now:
            rgbs = 0x11D6D0
            text = (
                f"## 📥 __{candidate_name}__ 📥\n"
                f"## > 📨 __DATA UPDATE!__ 📨\n"
                f"- Everyone will be forced to update {'at ' if not relative else ''}"
                f"{format_time_view(int(time_post), relative, 'f')}."
            )
        elif time_down and time_back and int(time_back) > now:
            t_down, t_back = int(time_down), int(time_back)
            if t_down > now:
                rgbs = 0xFCD703
                text = (
                    f"## ⚠️ __{candidate_name}__ ⚠️\n"
                    f"## > ℹ️ __MAINTENANCE SCHEDULE!__ ℹ️\n"
                    f"- The maintenance operations will start {'at ' if not relative else ''}{format_time_view(t_down, relative, 'f')}.\n"
                    f"- Service should be restored {'at ' if not relative else ''}{format_time_view(t_back, relative, 'f')}."
                )
            else:
                rgbs = 0xFC2803
                text = (
                    f"## 🚧 __{candidate_name}__ 🚧\n"
                    f"## > 🔴 __SERVERS OFFLINE!__ 🔴\n"
                    f"- The maintenance operations started {'at ' if not relative else ''}{format_time_view(t_down, relative, 'f')}.\n\n"
                    f"## > 🟢 __ETA OF THE MAINTENANCE__ 🟢\n"
                    f"- Service is expected to be restored {'on ' if not relative else ''}{format_time_view(t_back, relative, 'f')}."
                )

    container = ui.Container(accent_colour=rgbs)
    if candidate_data and candidate_data.get("article_logo"):
        gallery = ui.MediaGallery()
        gallery.add_item(media=candidate_data["article_logo"])
        container.add_item(gallery)

    container.add_item(ui.TextDisplay(text))
    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="status", relative=relative)
    view.add_item(container)
    return view