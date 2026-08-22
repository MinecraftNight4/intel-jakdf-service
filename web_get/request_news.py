from concurrent.futures import ThreadPoolExecutor, as_completed
from logger import info, warn, crit, log
from datetime import datetime, timezone
from bs4 import BeautifulSoup
import requests
import hashlib
import json
import math
import os
import re


class KaijuReadNews:
    def __init__(self, storage_file="sys_save/request_news.json"):
        self.storage_file = storage_file
        self.news_storage = {}

    def storage_data_news(self):
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            
            with open(self.storage_file, 'w', encoding='utf-8') as f:
                json.dump(self.news_storage, f, ensure_ascii=False, indent=4)
            
            log(f"SAVING: The Database stored x{len(self.news_storage)} news", "news", show=False)
        except Exception as e:
            log(f"SAVING: Something went wrong: {e}", "news", level="CRIT", show=False)
    
    
    
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
                new_lines.append(f"\\**{content}*")
            else:
                new_lines.append(line)
        text = "\n".join(new_lines)
        return text.strip()

    def tool_for_raws(self, element) -> str:
        try:
            text = element.get_text(strip=False)
        except:
            return ""
        return text.strip()

    def tool_for_colors(self, category: str) -> str:
        category = category.lower().strip() if category else ""
    
        colors = {
            "maintenance": "455a64",
            "important": "e53935",
            "update": "1e88e5",
            "event": "43a047",
            "gacha": "8e24aa",
            "news":  "546e7a",
            "known issue": "fb8c00",
        }
        return colors.get(category, "ffffff")
 
    def tool_for_limit(self, buffer, tag) -> bool:
        if tag in ("h1", "h2", "h3"):
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
        except:
            post_time = ""

        self.news_storage[news_id]["article_time"] = int(self.transform_unix(post_time, False))
        body_container = soup.select_one("div.ui-contents-main-detail.js-detail-body")
        if not body_container:
            return

        elements = body_container.select("h2, h3, p, li, img, table")
        buffer_item = ""
        buffer_raws = ""
        for el in elements:
            tag = el.name

            if tag == "img":
                img_url = el.get("src")
                if img_url:
                    if self.news_storage[news_id]["article_logo"] is None:
                        self.news_storage[news_id]["article_logo"] = img_url
                    else:
                        if buffer_item.strip() != "":
                            self.news_storage[news_id]["article_raws"].append(buffer_raws.strip())
                            self.news_storage[news_id]["article_item"].append(buffer_item.strip())
                            self.news_storage[news_id]["article_node"].append("txt")
                            buffer_item = ""
                            buffer_raws = ""
                        self.news_storage[news_id]["article_raws"].append("[ATTACHMENT]")
                        self.news_storage[news_id]["article_item"].append(img_url)
                        self.news_storage[news_id]["article_node"].append("img")
                        continue

            if tag == "table":
                table_lines = self.transform_table(el, news_id)
                for table_text in table_lines:
                    if self.tool_for_limit(f"{buffer_item}{table_text}", tag) == True:
                        self.news_storage[news_id]["article_raws"].append(buffer_raws.strip())
                        self.news_storage[news_id]["article_item"].append(buffer_item.strip())
                        self.news_storage[news_id]["article_node"].append("txt")
                        buffer_item = ""
                        buffer_raws = ""
                    buffer_raws += f"[TABLE ITEM]⤷"
                    buffer_item += f"{table_text}\n"
                continue

            text_raws = self.tool_for_raws(el)
            text_form = self.tool_for_text(el, news_id)
            if self.tool_for_limit(f"{buffer_item}{text_form}", tag) == True:
                if buffer_item.strip() != "":
                    self.news_storage[news_id]["article_raws"].append(buffer_raws.strip())
                    self.news_storage[news_id]["article_item"].append(buffer_item.strip())
                    self.news_storage[news_id]["article_node"].append("txt")
                    buffer_item = ""
                    buffer_raws = ""
            if tag == "li":
                buffer_item += f"- {text_form}\n"
                buffer_raws += f"{text_raws}⤷"
            elif tag == "h2":
                buffer_item += f"## __{text_form.upper()}__\n"
                buffer_raws += f"{text_raws}⤷"
            elif tag == "h3":
                buffer_item += f"### __{text_form.upper()}__\n"
                buffer_raws += f"{text_raws.upper()} "
            elif tag == "p":
                parent_tag = el.parent.name.lower() if el.parent else ""
                if parent_tag in ("td", "th"):
                    continue
                buffer_item += f"{text_form}\n"
                buffer_raws += f"{text_raws}⤷"
        if buffer_item.strip():
            if buffer_item.strip() != "":
                self.news_storage[news_id]["article_raws"].append(buffer_raws.strip())
                self.news_storage[news_id]["article_item"].append(buffer_item.strip())
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
            log(f"[ARTICLE {news_id}]: [WRITE: 🔁] [STATUS: 🔁] [TIME: 🔁] [URL: {url}]", "news", show=False)
            response = requests.get(url, timeout=60)
            log(f"[ARTICLE {news_id}]: [WRITE: 🔁] [STATUS: {response.status_code}] [TIME: {response.elapsed}] [URL: {url}]", "news", show=False)
            response.raise_for_status()
            self.scan_news(news_id, response.text)
            log(f"[ARTICLE {news_id}]: [WRITE: ✅] [STATUS: {response.status_code}] [TIME: {response.elapsed}] [URL: {url}]", "news", show=False)
            return news_id, True
        except Exception as e:
            log(f"[ARTICLE {news_id}]: [FAILURE: 🚫] {e}", "news", level="CRIT", show=False)
            return news_id, False

    def scan_index(self, batch_size: int = 3):
        log(f"NEWS UUID INDEX: [Reading...]", "news", show=False)
        try:
            response = requests.get('https://info.kj8-thegame.com/news?language=en', timeout=60)
            response.raise_for_status()
        except Exception as e:
            log(f"NEWS UUID INDEX: [Failure] {e}", "news", level="CRIT", show=False)
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        articles = soup.select("div.ui-list-block.js-each-content")
        self.news_storage.clear()
        
        log(f"NEWS UUID INDEX: [Success] - x{len(articles)} ITEMS", "news", show=False)
        
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
                "article_raws": [],
                "article_item": [],
                "article_unix": []
            }

        news_ids = list(self.news_storage.keys())        
        math_all = math.ceil(len(news_ids) / batch_size)
        math_eta = math_all * 3
        log(f"NEWS UUID READ: [x{batch_size} Items per batch] [x{math_all} Batch] [ETA: {math_eta}s]", "news", show=False)
        
        # === Procesamiento en paralelo por lotes ===
        with ThreadPoolExecutor(max_workers=batch_size) as executor:
            for i in range(0, len(news_ids), batch_size):
                log(f"NEWS UUID READ: [BATCH N°{i//batch_size + 1}]", "news", show=False)
                batch = news_ids[i:i + batch_size]
                future_to_id = {executor.submit(self.fetch_single_news, nid): nid for nid in batch}
                for future in as_completed(future_to_id):
                    news_id, success = future.result()

        log(f"NEWS UUID READ: [CLOSED] [x{len(self.news_storage)} ITEMS]", "news", show=False)

    
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