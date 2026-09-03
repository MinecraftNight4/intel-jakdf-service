# cogs/calendar/event.py
from discord import ui
from .helpers import (
    load_json, now_unix, format_ts, FlavorTextOnTime,
    GenerateUnixDay, NEWS_FILE
)
from .base import add_navigation_buttons

def panelbuilder_events(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x43a047)

    container.add_item(ui.TextDisplay("## __CURRENT CALENDAR:__"))
    container.add_item(ui.Separator())

    news = load_json(NEWS_FILE, {})
    night = GenerateUnixDay(16)
    lines = []

    for art in news.values():
        if (art.get("article_type") or "").lower() != "event":
            continue
        name = (art.get("article_name") or "").upper()
        unixes = art.get("article_unix") or []
        if not unixes:
            continue

        max_ts = max(unixes)
        # Opcional: saltar eventos completamente expirados
        if max_ts <= now_unix():
            continue

        u1 = unixes[0]
        u2 = unixes[1] if len(unixes) > 1 else max_ts
        u3 = unixes[2] if len(unixes) > 2 else max_ts

        if "RAID BATTLE" in name:
            if name.startswith("[UPDATED]"):
                clean = name.replace("[UPDATED] ", "")
                block = (
                    f"### `RAID` **__{clean}__**\n"
                    f"> 📆 [__THREAT DEFEATED!__] The event ends {format_ts(max_ts, relative, 'd')}¹.\n"
                    f"- 📬 Ranking rewards should be sent on {format_ts(u1 + 172800, relative, 'd')}.\n"
                    f"- ⚠️ Unclaimed rewards will not be mailed."
                )
            else:
                block = (
                    f"### `RAID` **__{name}__**\n"
                    f"> ⚠️ [__THREAT IS ALIVE!__]\n"
                    f"- 🔁 You can claim x3 Free Battle Permits {format_ts(night, relative, 't')}.\n"
                    f"- ℹ️ *It's not possible to display the remaining life in real time.*"
                )
        elif "KAIJU RUSH" in name:
            rush_parts = []
            for i, ts in enumerate(unixes[1:5], 1):
                if ts > now_unix():
                    rush_parts.append(f"`{i}: ❌` {format_ts(ts, relative, 'd')}")
                else:
                    rush_parts.append(f"`{i}: ☑️`")
            rush_txt = ", ".join(rush_parts)
            block = (
                f"### `RUSH` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹.\n"
                f"- 🗓️ Area unlock dates: {rush_txt}"
            )
        elif "TOTAL WAR" in name:
            ticket_reset = max(unixes)
            playable = FlavorTextOnTime(
                u2,
                f"- 🎮 The event will be unplayable {format_ts(u2, relative, 'd')}.\n"
                f"- 🔁 The free event ticket resets {format_ts(ticket_reset, relative, 't')}.",
                "- 🔒 The event is no longer playable."
            )
            block = (
                f"### `TOTAL WAR` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u3, relative, 'd')}¹.\n"
                f"{playable}"
            )
        elif "BATTLE AREA (LIMITED)" in name:
            block = (
                f"### `BATTLE ARENA` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹."
            )
        elif "MINI SPECIAL EVENT" in name or "SPECIAL EVENT" in name:
            unplayable = FlavorTextOnTime(
                u2,
                f"- 🎮 The event will be unplayable {format_ts(u2, relative, 'd')}.",
                "- 🔒 The event is no longer playable and you can only spend what you've earned."
            )
            block = (
                f"### `SPECIAL EVENT` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u3, relative, 'd')}¹.\n"
                f"{unplayable}"
            )
        elif "MOP-UP" in name:
            block = (
                f"### `MOBUP` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u1, relative, 'd')}¹.\n"
                f"- ℹ️ If there are 0 Kaiju remaining, the event will close automatically."
            )
        elif "MAIN STORY CH" in name:
            block = (
                f"### `STORY EVENT` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹."
            )
        elif "TRAINING:" in name:
            block = (
                f"### `TRAINING` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}².\n"
                f"- 🔁 This bonus applies to the first 10 clears and it's reset {format_ts(night, relative, 't')}."
            )
        elif "LARGE CONQUEST:" in name:
            block = (
                f"### `CONQUEST` **__{name}__**\n"
                f"> 📆 The event ends {format_ts(u2, relative, 'd')}¹.\n"
                f"- ⚠️ Unclaimed rewards will not be mailed."
            )
        else:
            block = (
                f"### **__{name}__**\n"
                f"> 📆 Ends {format_ts(max_ts, relative, 'd')}."
            )
        lines.append(block)

    text = "\n\n".join(lines) if lines else "*No active events found.*"
    container.add_item(ui.TextDisplay(text))

    daily = GenerateUnixDay(0)
    night = GenerateUnixDay(16)
    container.add_item(ui.TextDisplay(
        f"ℹ️ Depending on the type of event, these are updated at "
        f"{format_ts(daily, False, 't')}¹ or {format_ts(night, False, 't')}²."
    ))
    container.add_item(ui.Separator())
    add_navigation_buttons(container, current="events", relative=relative)
    view.add_item(container)
    return view