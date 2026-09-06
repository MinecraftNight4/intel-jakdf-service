# cogs/calendar/misc.py
from discord import ui
from .helpers import (
    format_time_view, generate_as_unix_week, generate_as_unix_month
)
from .base import add_navigation_buttons


def panelbuilder_resets(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x546e7a)

    weekly = generate_as_unix_week(7, 16)   # Domingo 16:00 JST
    monthly = generate_as_unix_month(16)

    text = (
        f"## PLACEHOLDER_REPLACE_schedule_defense_force_pass __DEFENSE FORCE PASS:__\n"
        f"- 📅 The current season pass ends {format_time_view(monthly, relative, 'f')}.\n"
        f"- 🚧 The weekly limit of 20,000 XP reset {format_time_view(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_weekly_medal __IDENTIFIED KAIJU NEUTRALIZATION:__\n"
        f"- 🚧 The weekly limit of 5 medals resets {format_time_view(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_store_stock __STORE - STOCKING:__\n"
        f"## > PLACEHOLDER_REPLACE_storetab_dce Restock {format_time_view(weekly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_es Restock {format_time_view(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_we Restock {format_time_view(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_c Restock {format_time_view(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_pov Restock {format_time_view(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_eod Restock {format_time_view(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_e Restock {format_time_view(monthly, relative, 'd')}."
    )
    container.add_item(ui.TextDisplay(text))
    container.add_item(ui.Separator())

    add_navigation_buttons(container, current="resets", relative=relative)
    view.add_item(container)
    return view