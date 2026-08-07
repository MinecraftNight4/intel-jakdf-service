from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests
import hashlib
import json
import os
import re


class KaijuReadNews:
    def __init__(self, storage_file="web_save/request_news.json"):
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

    
    def storage_file_news(self, file_url: str) -> str:
        if not file_url:
            return "web_save/request_news_error.jpg"
        if not file_url.startswith(("http://", "https://")):
            file_url = "https://info.kj8-thegame.com" + file_url.lstrip(".")
        filename = os.path.basename(file_url.split("?")[0].split("#")[0])
        if not filename or "." not in filename:
            filename = hashlib.md5(file_url.encode()).hexdigest() + ".bin"
    
        save_dir = "web_save/request_news"
        os.makedirs(save_dir, exist_ok=True)
        local_path = os.path.join(save_dir, filename).replace("\\", "/")
        
        if os.path.isfile(local_path):
            return local_path
        try:
            print(f"⬇️ Descargando: {file_url}")
            response = requests.get(file_url, timeout=120, stream=True)
            response.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            print(f"✅ Guardado en: {local_path}")
            return local_path
        except Exception as e:
            print(f"❌ Error al descargar {file_url}: {e}")
            return "web_save/request_news.jpg"

    
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
        text = text.replace("{;;nl;;}", "\n")
        text = re.sub(timestamp_regex, replace_ts, text)
        
        
        lines = text.split("\n")
        new_lines = []
        for line in lines:
            if line.startswith("*") and len(line) > 1 and not line[1].isspace():
                content = line[1:]
                new_lines.append(f"-# - *{content}*")
            else:
                new_lines.append(line)
        text = "\n".join(new_lines)
        return text.strip()
    


    def tool_for_colors(self, category: str) -> str:
        category = category.lower().strip() if category else ""
    
        colors = {
            "maintenance": "455a64",
            "important":   "e53935",
            "update":      "1e88e5",
            "event":       "43a047",
            "gacha":       "8e24aa",
            "news":        "546e7a",
            "known issue": "fb8c00",
        }
        return colors.get(category, "ffffff")
    
    
    def tool_for_limit(self, buffer, tag) -> bool:
        if tag in ("h1", "h2"):
            return True
        elif len(buffer) >= 700:
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
        if not rows:
            return [f"`TABLE ERROR: {len(rows)}`"]
        
        max_cols = 0
        for row in rows:
            max_cols = max(max_cols, len(row.select("td, th")))
        
        response_output = []
        last_values = [""] * max_cols
        
        for row_id, row in enumerate(rows, 1):
            cells = row.select("td, th")
            current_row = []
            cell_index = 0
            
            for col in range(max_cols):
                if cell_index < len(cells):
                    cell = cells[cell_index]
                    cell_index += 1
                    
                    paragraphs = cell.select("p")
                    if paragraphs:
                        texts = []
                        for p in paragraphs:
                            processed = self.tool_for_text(p, news_id)
                            if processed.strip():
                                texts.append(processed)
                            value = "\n> `❚ └─` ".join(texts) if texts else ""
                    else:
                        value = cell.get_text(strip=True, separator=" ")
                    last_values[col] = value
                    
                else:
                    value = last_values[col]
                
                current_row.append(value)
            
            row_output = ""
            for i, value in enumerate(current_row):
                row_output += f"> `❚ {i+1}:` {value}\n"
            
            final_row = f"`━ ROW {row_id} OF {len(rows)}:`\n{row_output.strip()}"
            response_output.append(final_row)
        return response_output
    
    
    
    
    
    
    
    
    
    
    
    def scan_news(self, news_id: str, html: str):
        html = html.replace("<br/>", "{;;nl;;}")
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
                    local_or_url = img_url#self.storage_file_news(img_url)
                    if self.news_storage[news_id]["article_logo"] is None:
                        self.news_storage[news_id]["article_logo"] = local_or_url
                    else:
                        if buffer.strip() != "":
                            self.news_storage[news_id]["article_item"].append(buffer.strip())
                            self.news_storage[news_id]["article_node"].append("txt")
                            buffer = ""
                        self.news_storage[news_id]["article_item"].append(local_or_url)
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
                buffer += f"> ## __`{text.upper()}`__\n"
            elif tag == "h3":
                buffer += f"> ### __`{text.upper()}`__\n"
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

        




    
    def fetch_single_news(self, news_id: str):
        try:
            url = f"https://info.kj8-thegame.com/news/{news_id}?language=en"
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            print(f"✓ Procesada: {news_id}")
            self.scan_news(news_id, response.text)
            return news_id, True
        except Exception as e:
            print(f"❌ Error leyendo {news_id}: {e}")
            return news_id, False
    
    def scan_index(self, batch_size: int = 3):
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

        # === Crear estructura base ===
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
                "article_rgbs": self.tool_for_colors(article_node),
                "article_logo": None,
                "article_hash": "0",
                "article_node": [],
                "article_item": [],
                "article_unix": []
            }

        news_ids = list(self.news_storage.keys())
        print(f"Se encontraron {len(news_ids)} noticias. Procesando en lotes de {batch_size}...\n")

        # === Procesamiento en paralelo por lotes ===
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            # Procesamos en lotes para no saturar el servidor
            for i in range(0, len(news_ids), batch_size):
                batch = news_ids[i:i + batch_size]
                print(f"→ Procesando lote {i//batch_size + 1} ({len(batch)} noticias)...")
                
                future_to_id = {executor.submit(self.fetch_single_news, nid): nid for nid in batch}
                
                for future in as_completed(future_to_id):
                    news_id, success = future.result()

        print(f"\nFinalizado. Total de noticias en memoria: {len(self.news_storage)}")
    
    
# ====================== EJECUCIÓN ======================

if __name__ == "__main__":
    processor = KaijuReadNews()
    
    # ==================== EJECUTAR EL SCRAPER ====================
    processor.scan_index(batch_size=4)   # Cambia a False si quieres procesar todas las noticias
    
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