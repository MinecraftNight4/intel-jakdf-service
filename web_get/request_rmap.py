import os
import json
import requests
import cv2
import numpy as np
from io import BytesIO
from PIL import Image

# -------------------------------------------------
# Configuración
# -------------------------------------------------
XCOM_FILE = "sys_save/request_xcom.json"
OUTPUT_DIR = "sys_save/debug_crops"          # Aquí se guardan los recortes
DEBUG_DIR = "sys_save/debug_detection"       # Aquí se guardan las imágenes con cajas dibujadas

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# -------------------------------------------------
# Utilidades
# -------------------------------------------------
def download_image(url: str) -> Image.Image:
    print(f"  Descargando: {url}")
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def pil_to_cv2(pil_img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)


def cv2_to_pil(cv_img: np.ndarray) -> Image.Image:
    return Image.fromarray(cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB))


# -------------------------------------------------
# Detección visual (versión más agresiva + debug)
# -------------------------------------------------
def detect_event_boxes(cv_img: np.ndarray, post_id: str) -> list[tuple[int, int, int, int]]:
    h, w = cv_img.shape[:2]
    print(f"  Tamaño imagen: {w}x{h}")

    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    # --- Versión A: Canny clásico ---
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 20, 80)          # umbrales más bajos = más sensibles

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5))
    closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    print(f"  Contornos encontrados: {len(contours)}")

    boxes = []
    img_area = w * h

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 3000:                         # mínimo muy bajo
            continue

        x, y, bw, bh = cv2.boundingRect(cnt)
        aspect = bw / float(bh) if bh > 0 else 0

        # Filtros muy permisivos para empezar
        if aspect < 1.5 or aspect > 7.0:
            continue
        if bh < 50 or bw < 150:
            continue
        if area / (bw * bh) < 0.5:
            continue

        # Evitar solo el header y footer extremos
        if y < 80:
            continue
        if y + bh > h - 80:
            continue

        boxes.append((x, y, bw, bh))

    # Ordenar
    boxes = sorted(boxes, key=lambda b: (b[1] // 40, b[0]))

    # Eliminar duplicados fuertes
    final = []
    for box in boxes:
        x, y, bw, bh = box
        overlap = False
        for fx, fy, fw, fh in final:
            inter_x1 = max(x, fx)
            inter_y1 = max(y, fy)
            inter_x2 = min(x + bw, fx + fw)
            inter_y2 = min(y + bh, fy + fh)
            if inter_x2 > inter_x1 and inter_y2 > inter_y1:
                inter = (inter_x2 - inter_x1) * (inter_y2 - inter_y1)
                if inter / (bw * bh) > 0.4:
                    overlap = True
                    break
        if not overlap:
            final.append(box)

    print(f"  Cajas finales después de filtros: {len(final)}")

    # --- Guardar imagen de debug ---
    debug_img = cv_img.copy()
    for i, (x, y, bw, bh) in enumerate(final):
        cv2.rectangle(debug_img, (x, y), (x + bw, y + bh), (0, 255, 0), 3)
        cv2.putText(debug_img, str(i), (x + 5, y + 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    debug_path = os.path.join(DEBUG_DIR, f"{post_id}_detection.png")
    cv2.imwrite(debug_path, debug_img)
    print(f"  Debug guardado → {debug_path}")

    return final


# -------------------------------------------------
# Main (solo descarga + recorte)
# -------------------------------------------------
def main():
    if not os.path.exists(XCOM_FILE):
        print(f"[ERROR] No existe {XCOM_FILE}")
        return

    with open(XCOM_FILE, "r", encoding="utf-8") as f:
        xcom_data = json.load(f)

    for account_name, account_data in xcom_data.items():
        roadmap = account_data.get("roadmap", {})

        for post_id, entry in roadmap.items():
            post_id = str(post_id)
            image_url = entry.get("preview")
            if not image_url:
                continue

            print(f"\n[SCAN] {account_name} → {post_id}")

            try:
                # 1. Descargar
                original_pil = download_image(image_url)
                cv_img = pil_to_cv2(original_pil)

                # 2. Detectar cajas
                boxes = detect_event_boxes(cv_img, post_id)

                if not boxes:
                    print("  [WARN] 0 tarjetas detectadas")
                    continue

                # 3. Recortar y guardar cada una
                for i, (x, y, w, h) in enumerate(boxes):
                    # Pequeño padding
                    pad = 4
                    x1 = max(0, x - pad)
                    y1 = max(0, y - pad)
                    x2 = min(cv_img.shape[1], x + w + pad)
                    y2 = min(cv_img.shape[0], y + h + pad)

                    crop = cv_img[y1:y2, x1:x2]
                    crop_pil = cv2_to_pil(crop)

                    out_path = os.path.join(OUTPUT_DIR, f"{post_id}_card_{i:02d}.png")
                    crop_pil.save(out_path, quality=95)
                    print(f"  Guardado: {out_path}  ({w}x{h})")

                print(f"  → Total recortadas: {len(boxes)}")

            except Exception as e:
                print(f"  [ERROR] {e}")
                import traceback
                traceback.print_exc()


if __name__ == "__main__":
    main()