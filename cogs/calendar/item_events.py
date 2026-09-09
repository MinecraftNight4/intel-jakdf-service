# cogs/calendar/item_events.py
import re
from discord import ui
from collections import defaultdict
from .helpers import (
    fetchjson, now_as_unix, format_time_view, format_text_view,
    generate_as_unix_day, event_get_unimaterial, NEWS_FILE
)
from .base import add_navigation_buttons

def cleartext(text: str) -> str:
    patterns = [r"\[UPDATED\]\s*", r"\s*NOW AVAILABLE!", r"TRAINING:\s*"]
    for pattern in patterns:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return text

def panelbuilder_events(relative: bool = False) -> ui.LayoutView:
    #===================#
    #   RETRIEVE DATA   #
    #===================#
    data_layout = ui.LayoutView()
    data_buider = ui.Container(accent_colour=0x43a047)
    data_temp_news = fetchjson(NEWS_FILE, {})
    data_temp_list: dict[int, list[str]] = defaultdict(list)
    data_temp_time = now_as_unix()
    data_temp_1600 = generate_as_unix_day(16)
    
    #====================#
    #   CALENDAR BUILDER #
    #====================#
    for art in data_temp_news.values():
        # === ARTICLE FILTER ===
        if (art.get("article_type") or "").lower() != "event":
            continue
        if len(art.get("article_unix") or []) == 0:
            continue
        if max(art.get("article_unix") or []) <= data_temp_time:
            continue
        
        # === ARTICLE STORAGE ===
        candidate_unix = (art.get("article_unix") or [])
        candidate_name = (art.get("article_name") or "").upper()
        hv_1 = candidate_unix[0]
        hv_2 = candidate_unix[1] if len(candidate_unix) > 1 else max(candidate_unix)
        hv_3 = candidate_unix[2] if len(candidate_unix) > 2 else max(candidate_unix)
        
        # === EVENT TRANSCRIPTION ===
        if "RAID BATTLE" in candidate_name:
            if candidate_name.startswith("[UPDATED] "):
                candidate_name = cleartext(candidate_name)
                info_unix = max(candidate_unix)
                info_text = f"  - 🗡️ `🠟 [DEATH] {candidate_name} 🠟` \n    - [`🎁` Rank Rewards] should be sent {'at ' if not relative else ''}{format_time_view((hv_1 + 172800), relative, 'd')}"
                
            else:
                candidate_name = cleartext(candidate_name)
                info_unix = max(candidate_unix)
                info_text = f"  - 🗡️ `🠟 [ALIVE] {candidate_name} 🠟` \n    - [`🎫` Free Permits] resets {'at ' if not relative else ''}{format_time_view(data_temp_1600, relative, 'f')}"
                
                
        elif "KAIJU RUSH" in candidate_name:
            kr_unix = sorted(candidate_unix)
            kr_path = []
            kr_uuid = 1
            
            for ts in kr_unix:
                if max(candidate_unix) == ts:
                    continue
                elif ts > data_temp_time:
                    kr_path.append(f"`{kr_uuid}: ❌` {format_time_view(ts, relative, 'd')}")
                    kr_uuid += 1
                else:
                    kr_path.append(f"`{kr_uuid}: ☑️`")
                    kr_uuid += 1
            kr_path = ", ".join(kr_path)
            info_unix = hv_2
            candidate_name = cleartext(candidate_name)
            info_text = f"  - 🗺️ `🠟 {candidate_name} 🠟` \n    - [`🔓` Unlocks: {kr_path}]"
        


        elif "TOTAL WAR" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_3
            info_text = f"  - 🪖 `🠟 {candidate_name} 🠟` \n      - [🎮 The event won't be playable {'on ' if not relative else ''}{format_time_view(hv_2, relative, 'd')}]"


        elif "MINI SPECIAL EVENT" in candidate_name or "SPECIAL EVENT" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_3
            info_text = format_text_view(hv_2, f"[🎮 The event won't be playable {'on ' if not relative else ''}{format_time_view(hv_2, relative, 'd')}]", f"[🚧 Claim your pending rewards!]")
            info_text = f"  - 📖 `🠟 {candidate_name} 🠟` \n      - {info_text}"
        
        
        elif "MOB-UP" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_1
            info_text = f"  - 🧟 `🠟 {candidate_name} 🠟` \n      - [🧵 Unipart(s): {event_get_unimaterial(art)}]"
        
            
        elif "BATTLE AREA (LIMITED)" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_2
            info_text = f"  - 🛡️ `{candidate_name}`"
        
        
        elif "MAIN STORY" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_2
            info_text = f"  - 📖 `{candidate_name}`"
            
            
        elif "TRAINING:" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = hv_2
            info_text = f"  - ⚒️ `{candidate_name}`"
            
            
        elif "LARGE CONQUEST:" in candidate_name:
            info_unix = hv_2
            candidate_name = cleartext(candidate_name)
            info_text = f"  - 📖 `{candidate_name}`"    
        
        elif "DIMENSIONAL SWARM DISASTER" in candidate_name:
            candidate_name = cleartext(candidate_name)
            info_unix = max(candidate_unix)
            info_text = f"  - ⛈️ `{candidate_name}`"
        
        else:
            candidate_name = cleartext(candidate_name)
            info_unix = max(candidate_unix)
            info_text = f"  - 📦 `{candidate_name}`"
    
    
        data_temp_list[info_unix].append(info_text)
    data_temp_sort = sorted(data_temp_list.keys(), reverse=True)
    
    #=================#
    #   EMBED BUIDER  #
    #=================#
    data_buider.add_item(ui.TextDisplay("## __ACTIVE EVENTS IN-GAME:__"))
    data_buider.add_item(ui.Separator())
    
    if not data_temp_sort:
        data_buider.add_item(ui.TextDisplay("## __WELP... THIS IS EMPTY... `≡(▔﹏▔)≡`__"))
    else:
        text_display_all = []
        for ts in data_temp_sort:
            display_of_date = f"- **__Departing {'on ' if not relative else ''}{format_time_view(ts, relative, 'f')}:__**"
            display_of_data = "\n".join(data_temp_list[ts])
            text_display_all.append(f"{display_of_date}\n{display_of_data}")
        data_buider.add_item(ui.TextDisplay( "\n\n".join(text_display_all)) )
    
    data_buider.add_item(ui.Separator())
    add_navigation_buttons(data_buider, current="events", relative=relative)
    data_layout.add_item(data_buider)
    return data_layout