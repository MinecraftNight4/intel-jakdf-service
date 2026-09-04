# cogs/calendar/base.py
import discord
from discord import ui
from .helpers import status_show_display



def add_navigation_buttons(container: ui.Container, current: str, relative: bool = False):
    show_type = "a" if relative else "b"
    show_type_switch = "b" if relative else "a"
    
    #=======================
    # ROW 1
    #=======================
    row1 = ui.ActionRow()
    # GAME SERVICE STATUS
    show_update = status_show_display()
    print
    if show_update:
        row1.add_item(ui.Button(label="STATUS", style=discord.ButtonStyle.danger, custom_id=f"schedule_status_{show_type}", emoji="⚠️", disabled=(current == "status") ))
    
    # OTHER VISUAL TABS
    style = discord.ButtonStyle.success
    row1.add_item(ui.Button(label="GACHAS", style=style, custom_id=f"schedule_gachas_{show_type}", emoji="🎫", disabled=(current == "gachas") ))
    row1.add_item(ui.Button(label="EVENTS", style=style, custom_id=f"schedule_events_{show_type}", emoji="🎪", disabled=(current == "events") ))
    row1.add_item(ui.Button(label="COMING", style=style, custom_id=f"schedule_coming_{show_type}", emoji="🗺️", disabled=(current == "coming") ))
    row1.add_item(ui.Button(label="RESETS", style=style, custom_id=f"schedule_resets_{show_type}", emoji="🏪", disabled=(current == "resets") ))
    container.add_item(row1)
    
    #=======================
    # ROW 2
    #=======================
    button_txt = "Countdowns: Yes" if relative else "Countdowns: No"
    button_ico = "⏳" if relative else "🗓️"

    # 1. Crear el bloque de texto de la sección
    # Se pasa 'accessory' obligatoriamente como argumento con nombre en el constructor
    row2 = ui.Section(
        ui.TextDisplay(
            "-# ℹ️ Discord adjusted the dates to your time zone!\n"
            "-# 🔄 The countdown changes the format of the displayed dates."
        ),
        accessory=ui.Button(
            label=button_txt,
            emoji=button_ico,
            style=discord.ButtonStyle.secondary,
            custom_id=f"schedule_{current}_{show_type_switch}"
        )
    )

    container.add_item(row2)