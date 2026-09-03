# cogs/calendar/base.py
import discord
from discord import ui
from .helpers import has_active_maintenance


def add_navigation_buttons(container: ui.Container, current: str, relative: bool = False):
    show_type = "a" if relative else "b"
    show_type_switch = "b" if relative else "a"
    
    #=======================
    # ROW 1
    #=======================
    row = ui.ActionRow()
    # GAME SERVICE STATUS
    show_update = True #has_active_maintenance()
    if show_update:
        row.add_item(ui.Button(label="STATUS", style=discord.ButtonStyle.danger, custom_id=f"schedule_status_{show_type}", emoji="⚠️", disabled={current == "status"}))
    
    # OTHER VISUAL TABS
    style = discord.ButtonStyle.success
    row.add_item(ui.Button(label="GACHAS", style=style, custom_id=f"schedule_gachas_{show_type}", emoji="🎫", disabled={current == "gachas"}))
    row.add_item(ui.Button(label="EVENTS", style=style, custom_id=f"schedule_events_{show_type}", emoji="🎪", disabled={current == "events"}))
    row.add_item(ui.Button(label="COMING", style=style, custom_id=f"schedule_coming_{show_type}", emoji="🗺️", disabled={current == "coming"}))
    row.add_item(ui.Button(label="RESETS", style=style, custom_id=f"schedule_resets_{show_type}", emoji="🏪", disabled={current == "resets"}))
    container.add_item(row)
    
    #=======================
    # ROW 2
    #=======================
    row = ui.ActionRow()
    
    button_txt = "Countdowns: Yes" if relative else "Countdowns: No"
    button_ico = "⏳" if relative else "🗓️"
    row.add_item(ui.Button(label=button_txt, emoji=button_ico, style=discord.ButtonStyle.primary, custom_id=f"schedule_{current}_{show_type_switch}"))
    row.add_item(ui.Button(label="Displayed time is based on your device!", style=discord.ButtonStyle.secondary, custom_id=f"schedule_display_info", disabled=True))
    container.add_item(row)