# cogs/calendar/misc.py
from discord import ui
from .helpers import (
    format_ts, GenerateUnixWeek, GenerateUnixMonth
)
from .base import add_navigation_buttons


def panelbuilder_resets(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x546e7a)

    weekly = GenerateUnixWeek(7, 16)   # Domingo 16:00 JST
    monthly = GenerateUnixMonth(16)

    text = (
        f"## PLACEHOLDER_REPLACE_schedule_defense_force_pass __DEFENSE FORCE PASS:__\n"
        f"- 📅 The current season pass ends {format_ts(monthly, relative, 'f')}.\n"
        f"- 🚧 The weekly limit of 20,000 XP reset {format_ts(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_weekly_medal __IDENTIFIED KAIJU NEUTRALIZATION:__\n"
        f"- 🚧 The weekly limit of 5 medals resets {format_ts(weekly, relative, 'f')}.\n\n"
        f"## PLACEHOLDER_REPLACE_schedule_store_stock __STORE - STOCKING:__\n"
        f"## > PLACEHOLDER_REPLACE_storetab_dce Restock {format_ts(weekly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_es Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_we Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_c Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_pov Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_eod Restock {format_ts(monthly, relative, 'd')}.\n"
        f"## > PLACEHOLDER_REPLACE_storetab_e Restock {format_ts(monthly, relative, 'd')}."
    )
    container.add_item(ui.TextDisplay(text))
    container.add_item(ui.Separator())

    add_navigation_buttons(container, current="resets", relative=relative)
    view.add_item(container)
    return view