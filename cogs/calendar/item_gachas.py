# cogs/calendar/gacha.py
from discord import ui
from .helpers import (
    fetchjson, now_as_unix, format_time_view, format_text_view,
    generate_as_unix_day, NEWS_FILE
)
from .base import add_navigation_buttons

def panelbuilder_gachas(relative: bool = False) -> ui.LayoutView:
    view = ui.LayoutView()
    container = ui.Container(accent_colour=0x8e24aa)

    container.add_item(ui.TextDisplay("## __CURRENT CALENDAR:__"))
    container.add_item(ui.Separator())

    news = fetchjson(NEWS_FILE, {})
    now = now_as_unix()
    lines = []

    for art in news.values():
        if (art.get("article_type") or "").lower() != "gacha":
            continue

        name = (art.get("article_name") or "").upper()
        unixes = art.get("article_unix") or []
        if len(unixes) < 2:
            continue

        end_banner = unixes[1]
        end_exchange = unixes[2] if len(unixes) > 2 else None

        # === CORRECCIÓN: No listar gachas ya expirados ===
        # Si el banner ya terminó y (si existe) el exchange también → saltar
        if end_banner <= now:
            if end_exchange is None or end_exchange <= now:
                continue

        if "PAID-ONLY" in name:
            left = "PLACEHOLDER_REPLACE_gacha_paid_left"
            right = "PLACEHOLDER_REPLACE_gacha_paid_right"
        elif "[LIMITED]" in name or "LIMITED" in name:
            left = "PLACEHOLDER_REPLACE_gacha_limited_left"
            right = "PLACEHOLDER_REPLACE_gacha_limited_right"
        else:
            left = "PLACEHOLDER_REPLACE_gachatype_pickup_left"
            right = "PLACEHOLDER_REPLACE_gachatype_pickup_right"

        banner_txt = format_text_view(
            end_banner,
            f"This banner leaves {format_time_view(end_banner, relative, 'f')}.",
            "The banner is no longer available."
        )
        exchange_txt = "N/A"
        if end_exchange:
            exchange_txt = format_text_view(
                end_exchange,
                f"The character leave the exchange {format_time_view(end_exchange, relative, 'f')}.",
                "N/A"
            )

        clean = (name.replace("PAID-ONLY ★5 ", "")
                     .replace("[LIMITED] ", "")
                     .replace(" PICKUP", "")
                     .replace(" GACHA", "")
                     .replace(" RERUN", "")
                     .replace(" NOW AVAILABLE!", ""))

        block = (
            f"### {left}{right} **{clean}:**\n"
            f"-#  - PLACEHOLDER_REPLACE_time_remaining_for_gacha {banner_txt}\n"
            f"-#  - PLACEHOLDER_REPLACE_time_remaining_for_exchange {exchange_txt}"
        )
        lines.append(block)

    text = "\n\n".join(lines) if lines else "*No active gachas found.*"
    container.add_item(ui.TextDisplay(text))

    daily = generate_as_unix_day(0)
    container.add_item(ui.TextDisplay(
        f"ℹ️ The availability of banners and exchanges are updated at {format_time_view(daily, False, 't')}."
    ))
    container.add_item(ui.Separator())

    add_navigation_buttons(container, current="gachas", relative=relative)
    view.add_item(container)
    return view