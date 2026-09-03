# cogs/calendar/base.py
import discord
from discord import ui

def add_navigation_buttons(container: ui.Container, current: str, relative: bool = False):
    """
    current: "update" | "gacha" | "event" | "soon" | "misc"
    """
    mode = "rel" if relative else "abs"

    styles = {
        "update": discord.ButtonStyle.danger if current == "update" else discord.ButtonStyle.primary,
        "gacha":  discord.ButtonStyle.success if current == "gacha" else discord.ButtonStyle.primary,
        "event":  discord.ButtonStyle.success if current == "event" else discord.ButtonStyle.primary,
        "soon":   discord.ButtonStyle.success if current == "soon" else discord.ButtonStyle.primary,
        "misc":   discord.ButtonStyle.success if current == "misc" else discord.ButtonStyle.primary,
    }

    # Forzar danger en UPDATE siempre
    styles["update"] = discord.ButtonStyle.danger

    row = ui.ActionRow()
    row.add_item(ui.Button(label="UPDATE!", style=styles["update"],
                           custom_id=f"schedule_update_{mode}", emoji="⚠️"))
    row.add_item(ui.Button(label="GACHAS", style=styles["gacha"],
                           custom_id=f"schedule_banner_{mode}", emoji="🎫"))
    row.add_item(ui.Button(label="EVENTS", style=styles["event"],
                           custom_id=f"schedule_event_{mode}", emoji="🎪"))
    row.add_item(ui.Button(label="SOON", style=styles["soon"],
                           custom_id=f"schedule_maps_{mode}", emoji="🗺️"))
    row.add_item(ui.Button(label="MISC", style=styles["misc"],
                           custom_id=f"schedule_misc_{mode}", emoji="🏪"))
    container.add_item(row)

    # Toggle Absolute / Remain
    toggle_row = ui.ActionRow()
    toggle_label = "View Absolute" if relative else "View Remain"
    toggle_row.add_item(ui.Button(
        label=toggle_label,
        style=discord.ButtonStyle.secondary,
        custom_id=f"schedule_toggle_{current}_{'abs' if relative else 'rel'}"
    ))
    container.add_item(toggle_row)