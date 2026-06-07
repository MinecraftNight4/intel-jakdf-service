from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests
import hashlib
import json
import os
import re


class KaijuReadNews:
    def __init__(self, storage_file="storage/news.json"):
        self.storage_file = storage_file
        self.news_storage = {}
    
    def storage_data_news(self):
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.news_storage, f, ensure_ascii=False, indent=4)
            
            print(f"✅ Archivo JSON guardado correctamente: {self.storage_file}")
            print(f"   Total de noticias guardadas: {len(self.news_storage)}")
        except Exception as e:
            print(f"❌ Error al guardar el JSON: {e}")
    
    def tool_for_text(self, element, newsid) -> str:
        try:
            text = element.get_text(strip=False)
        except:
            return ""
        #__URL MARKDOWNS__
        for a in element.select("a[href]"):
            href = a.get("href", "")
            htxt = a.get_text(strip=True)
            if htxt and href:
                if not href.startswith(("http://", "https://")):
                    href = "https://info.kj8-thegame.com/news" + href.lstrip(".")
                text = text.replace(htxt, f"[{htxt}]({href})", 1)
        #__UNIX CLEAR & TEXT CLEAR__
        timestamp_regex = r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})?\b"
        def replace_ts(match):
            unix = self.transform_unix(match.group(0), False, newsid)
            return f"<t:{unix}>"
        text = text.replace("'", "\\'")
        text = text.replace("{;;nl;;}", "\n")
        text = re.sub(timestamp_regex, replace_ts, text)
        return text.strip()

    def tool_for_limit(self, buffer, tag) -> bool:
        if len(buffer) >= 700:
            return True
        elif buffer.count("\n") >= 6:
            return True
        return False

        
    
    def transform_unix(self, time: str, format: bool = False, saveit: str = "SYNTAX ERROR") -> str:
        if not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(Z|[+-])", time):
            clean = re.sub(r"[TZ:-]", "", time)
            if clean.startswith("00"):
                clean = "20" + clean[2:]
            time = f"{clean[0:4]}-{clean[4:6]}-{clean[6:8]}T{clean[8:10]}:{clean[10:12]}:{clean[12:14]}Z"
        try:
            unix = int(datetime.fromisoformat(time.replace("Z", "+00:00")).timestamp())
        except:
            unix = int(datetime.now().timestamp())
        if saveit != "SYNTAX ERROR":
            if unix not in self.news_storage[saveit]["article_unix"]:
                self.news_storage[saveit]["article_unix"].append(unix)
        return str(unix) if (format == False) else str(f"<t:{unix}>")

    def transform_table(self, table, news_id) -> list[str]:
        rows = table.select("tr")
        if len(rows) <= 1:
            return [f"`TABLE ERROR: {len(rows)}`"]
        else:
            response_output = []
            prev_rows_dat = []
            max_cols = max(0, len(rows[0].select("td, th")) - 1)
    
            for row_id, row in enumerate(rows, 1):
                cells = row.select("td, th")
                now_row = []
                txt_row = {}
    
                for col_id in range(max_cols + 1):
                    if col_id >= len(cells):
                        now_row.append(prev_rows_dat[col_id] if col_id < len(prev_rows_dat) else "")
                        continue
    
                    cell = cells[col_id]
                    paragraphs = cell.select("p")
                    cell_texts = []
    
                    for p in paragraphs:
                        processed = self.tool_for_text(p, news_id)
                        if processed.strip():
                            cell_texts.append(processed)
                    if cell_texts:
                        joined = f"\n> `❚ └─` ".join(cell_texts)
                        txt_row[col_id] = f"{joined}\n"
                    else:
                        txt_row[col_id] = "\n"
                prev_rows_dat = list(txt_row.values())
                row_output = ""
                
                values = now_row if now_row else txt_row.values()
                for i, value in enumerate(values):
                    row_output += f"> `❚ {i+1}:` {value}"
                final_row = f"`━ ROW {row_id} OF {len(rows)}:`\n{row_output.strip()}"
                response_output.append(final_row)
            return response_output
                
    
    
    
    
    
    
    
    
    
    
    
    def scan_news(self, news_id: str, html: str):
        soup = BeautifulSoup(html, 'html.parser')
        try:
            post_time = soup.select_one("p.ui-contents-header-date span.nowrap").get_text(strip=True)
            title = soup.select_one("h1").get_text(strip=True)
        except:
            post_time = ""
            title = "Sin título"

        self.news_storage[news_id]["article_time"] = int(self.transform_unix(post_time, False))
        body_container = soup.select_one("div.ui-contents-main-detail.js-detail-body")
        if not body_container:
            return

        elements = body_container.select("h2, h3, p, li, img, table")
        buffer = ""
        for el in elements:
            tag = el.name

            if tag == "img":
                img_url = el.get("src")
                if img_url:
                    if self.news_storage[news_id]["article_logo"] is None:
                        self.news_storage[news_id]["article_logo"] = img_url
                    else:
                        if buffer.strip() != "":
                            self.news_storage[news_id]["article_item"].append(buffer.strip())
                            self.news_storage[news_id]["article_node"].append("txt")
                            buffer = ""
                        self.news_storage[news_id]["article_item"].append(img_url)
                        self.news_storage[news_id]["article_node"].append("img")
                        continue

            if tag == "table":
                table_lines = self.transform_table(el, news_id)
                for table_text in table_lines:
                    if self.tool_for_limit(f"{buffer}{table_text}", tag) == True:
                        self.news_storage[news_id]["article_item"].append(buffer.strip())
                        self.news_storage[news_id]["article_node"].append("txt")
                        buffer = ""
                    buffer += f"{table_text}\n"
                continue

            text = self.tool_for_text(el, news_id)
            if self.tool_for_limit(f"{buffer}{text}", tag) == True:
                if buffer.strip() != "":
                    self.news_storage[news_id]["article_item"].append(buffer.strip())
                    self.news_storage[news_id]["article_node"].append("txt")
                    buffer = ""
            if tag == "li":
                buffer += f"- {text}\n"
            elif tag == "h2":
                buffer += f"## __`{text.upper()}`__\n"
            elif tag == "h3":
                buffer += f"### __`{text.upper()}`__\n"
            elif tag == "p":
                parent_tag = el.parent.name.lower() if el.parent else ""
                if parent_tag in ("td", "th"):
                    continue
                buffer += f"{text}\n"
        if buffer.strip():
            if buffer.strip() != "":
                self.news_storage[news_id]["article_item"].append(buffer.strip())
                self.news_storage[news_id]["article_node"].append("txt")

        full_text = ""
        for item, node in zip(
            self.news_storage[news_id]["article_item"], 
            self.news_storage[news_id]["article_node"]
        ):
            if node == "txt":
                full_text += item + "\n\n"
        self.news_storage[news_id]["article_hash"] = hashlib.sha256(full_text.encode('utf-8')).hexdigest()

        




    def scan_index(self, debug_mode: bool = True):
        """Escanea el índice y procesa las noticias"""
        print("Iniciando scraper...")

        try:
            response = requests.get('https://info.kj8-thegame.com/news?language=en', timeout=60)
            response.raise_for_status()
        except Exception as e:
            print(f"Error al obtener índice: {e}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.select("div.ui-list-block.js-each-content")

        self.news_storage.clear()

        for article in articles:
            article_uuid = article.get("data-content-id")
            if not article_uuid:
                continue
                
            article_uuid = str(article_uuid)
            article_node = article.select_one("p.ui-list-category")
            article_node = article_node.get_text(strip=True).lower() if article_node else "unknown"
            article_name = article.select_one("div.ui-list-content")
            article_name = article_name.get_text(strip=True) if article_name else "SIN TÍTULO"

            self.news_storage[article_uuid] = {
                "article_name": article_name.upper(),
                "article_type": article_node,
                "article_uuid": article_uuid,
                "article_time": 120000,
                "article_logo": None,
                "article_hash": "0",
                "article_node": [],
                "article_item": [],
                "article_unix": []
            }

        for news_id in list(self.news_storage.keys()):
            try:
                response = requests.get(f"https://info.kj8-thegame.com/news/{news_id}?language=en", timeout=60)
            except Exception as e:
                print(f"Error leyendo {news_id}: {e}")
            if response.status_code == 200:
                print(f"✓ Procesada: {news_id}")
                self.scan_news(news_id, response.text)
                #break

        print(f"\nFinalizado. Total de noticias en memoria: {len(self.news_storage)}")
    
    
# ====================== EJECUCIÓN ======================

if __name__ == "__main__":
    processor = KaijuReadNews()
    
    # ==================== EJECUTAR EL SCRAPER ====================
    processor.scan_index(debug_mode=True)   # Cambia a False si quieres procesar todas las noticias
    
    # ==================== MOSTRAR RESULTADOS ====================
    print("\n" + "="*60)
    print("DATOS ALMACENADOS EN MEMORIA")
    print("="*60)
    
    for news_id, data in processor.news_storage.items():
        print(f"\n📰 NOTICIA: {news_id}")
        print(f"Título: {data.get('article_name', 'N/A')}")
        print(f"Tipo: {data.get('article_type', 'N/A')}")
        print(f"Hora: {data.get('article_time', 'N/A')}")
        print(f"Logo: {data.get('article_logo', 'N/A')}")
        print(f"Bloques guardados: {len(data.get('article_item', []))}")
        
        items = data.get('article_item', [])
        types = data.get('article_node', [])
        
        print("\nPrimeros bloques:")
        for i in range(len(items)):
            tipo = types[i] if i < len(types) else "?"
            content = items[i]
            
            print(f"\n[{tipo.upper()}]: {content}")
        
        print("-" * 50)
    processor.storage_data_news()