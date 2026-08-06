import json
import math
import os
from typing import Dict, Any, List

# ====================== CONFIGURACIÓN ======================
INPUT_JSON = "web_save/request_news.json"
OUTPUT_DIR = "app_read"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "read_news.json")

ARTICLE_ID = "1000030"
ITEMS_PER_PAGE = 4
ACCENT_COLOR = 0xFF8C00          # Naranja como en la captura
# ===========================================================

def make_button(label: str, custom_id: str, style: int = 2, disabled: bool = False, emoji: dict = None) -> dict:
    btn = {
        "type": 2,
        "style": style,
        "label": label,
        "custom_id": custom_id,
        "disabled": disabled
    }
    if emoji:
        btn["emoji"] = emoji
    return btn

def generate_components_v2(article: dict, page: int, per_page: int, total_pages: int) -> dict:
    """Genera un payload 100% compatible con Discord Components V2."""
    nodes = article["article_node"]
    items = article["article_item"]
    uuid = article["article_uuid"]

    start = (page - 1) * per_page
    end = start + per_page
    page_nodes = nodes[start:end]
    page_items = items[start:end]

    # ---------- Header ----------
    header_content = (
        f"## __{article['article_name']}__\n"
        f"[`🔗`](https://info.kj8-thegame.com/news/{uuid}"
        f"?language=en&platform=%22JAKDF%20INTEL%22%20-%20discord.gg%2Fkaijuno8) "
        f"Posted on <t:{article['article_time']}>."
    )

    # ---------- Componentes internos del Container ----------
    container_children: List[dict] = []

    # Logo (si existe) → Media Gallery
    if article.get("article_logo"):
        container_children.append({
            "type": 12,  # Media Gallery
            "items": [
                {
                    "media": {
                        "url": article["article_logo"]
                    }
                }
            ]
        })

    # Header
    container_children.append({
        "type": 10,  # Text Display
        "content": header_content
    })
    container_children.append({
        "type": 14,  # Separator
        "divider": True,
        "spacing": 1
    })

    # ---------- Contenido de la página (texto + imágenes) ----------
    current_text_parts: List[str] = []

    def flush_text():
        """Añade un Text Display con el texto acumulado (si hay algo)."""
        if current_text_parts:
            container_children.append({
                "type": 10,
                "content": "\n\n".join(current_text_parts)
            })
            current_text_parts.clear()

    for i, (node_type, content) in enumerate(zip(page_nodes, page_items), start=1):
        if node_type == "txt":
            current_text_parts.append(content)
        elif node_type == "img":
            # Primero vaciamos el texto pendiente
            flush_text()
            # Luego añadimos la imagen como Media Gallery
            container_children.append({
                "type": 12,  # Media Gallery
                "items": [
                    {
                        "media": {
                            "url": content   # ← aquí se usa la URL real de la imagen
                        }
                    }
                ]
            })
        else:
            current_text_parts.append(f"**[{start + i}] {node_type}**\n{content}")

    # Vaciar cualquier texto que haya quedado al final
    flush_text()

    # Si no había nada de contenido
    if len(container_children) <= 2:  # solo header + separator
        container_children.append({
            "type": 10,
            "content": "*Sin contenido en esta página*"
        })

    # ---------- Container (type 17) ----------
    container = {
        "type": 17,
        "accent_color": ACCENT_COLOR,
        "components": container_children
    }

    # ---------- Botones (Action Row) ----------
    buttons = [
        make_button("MENU", "gamenews_000000_1", style=4),
        make_button("BACK", f"gamenews_{uuid}_{page - 1}", style=3, disabled=page <= 1),
        make_button(f"{page}/{total_pages}", f"gamenews_{uuid}_jump", style=3),
        make_button("NEXT", f"gamenews_{uuid}_{page + 1}", style=3, disabled=page >= total_pages),
    ]

    action_row = {
        "type": 1,
        "components": buttons
    }

    return {
        "flags": 32768,  # IS_COMPONENTS_V2
        "components": [
            container,
            action_row
        ]
    }

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(INPUT_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    if ARTICLE_ID not in data:
        raise KeyError(f"Artículo '{ARTICLE_ID}' no encontrado")

    article = data[ARTICLE_ID]
    total_items = len(article["article_node"])
    total_pages = math.ceil(total_items / ITEMS_PER_PAGE) if total_items > 0 else 1

    output: Dict[str, Any] = {}

    for page in range(1, total_pages + 1):
        key = f"gamenews_{article['article_uuid']}_{page}"
        output[key] = generate_components_v2(article, page, ITEMS_PER_PAGE, total_pages)

    # Placeholder del menú
    output["gamenews_000000_1"] = {
        "flags": 32768,
        "components": [
            {
                "type": 10,
                "content": "## Menú de Noticias\nSelecciona una noticia o regresa."
            }
        ]
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"✅ Archivo generado: {OUTPUT_FILE}")
    print(f"Keys: {list(output.keys())}")
    print(f"Total páginas: {total_pages}")
    print("\nUso en discord.py / nextcord:")
    print("await interaction.response.edit_message(**news_data[interaction.custom_id])")

if __name__ == "__main__":
    main()