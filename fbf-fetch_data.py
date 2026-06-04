"""
fetch_data.py
Corre en GitHub Actions cada 30 minutos.
- Primera vez: descarga todo desde el 2026-05-01
- Siguientes veces: solo descarga las órdenes nuevas (desde el último registro)
- Guarda/actualiza data.csv en el repo
"""

import hashlib
import hmac
import urllib.parse
import requests
from datetime import datetime, timezone
import pandas as pd
import unicodedata
import os
import sys

USER_ID  = os.environ["FALABELLA_USER_ID"]
API_KEY  = os.environ["FALABELLA_API_KEY"]
BASE_URL = "https://sellercenter-api.falabella.com/"
CSV_PATH = "data.csv"
FECHA_INICIO = "2026-05-01T00:00:00+00:00"

# ── Normalización y extracción ────────────────────────────────────────────────
def norm(texto):
    texto = texto.upper()
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")

MARCAS = [
    "PANAMA JACK", "PJACK", "16 HRS", "BRUNO ROSSI", "ZAPPA", "POLLINI",
    "DAKOTA", "ENDURO", "IBIZAS HERITAGE", "LUZ DA LUA", "MINGO",
    "SHERPAS", "SHERPA S", "PLUMA",
]
LINEAS_CALZADO = [
    "FLIP FLOP", "BALLERINA", "PANTUFLA", "ZAPATILLA", "SANDALIA",
    "MAFALDA", "MOCASIN", "ZAPATO", "BOTIN", "BOTA", "ALPARGATA",
]
LINEAS_ROPA = [
    "POLERA MANGA LARGA", "POLERA MANGA CORTA", "POLERA PIQUE",
    "POLERA MC", "POLERA ML", "POLERON", "POLERA",
    "CAMISA MANGA LARGA", "CAMISA MANGA CORTA", "CAMISA ML", "CAMISA MC", "CAMISA",
    "PARKA ML", "PARKA MC", "PARKA",
    "BERMUDA", "BUZO", "CHAQUETA", "CORTAVIENTO", "GORRO",
    "JEANS", "JOCKEY", "JOGGER", "PANTALON", "POLAR", "SHORT", "TRAJE DE BANO",
]
LINEAS_BAGS = [
    "BACKPACK", "BANANO", "BANDANAS", "BANDANA", "BANDOLERA",
    "BILLETERA", "BOLSO", "CARTERA", "CINTURON", "CORREA",
    "GORRO", "GUANTES", "MALETA", "MOCHILA", "MONEDERO",
    "PORTA", "RINONERA", "SOBRE", "TOTE",
]
LINEAS_ACCESORIOS = [
    "CALCETINES", "CALCETA", "MEDIA ", "MEDIAS", "PLANTILLA",
    "CORDONES", "GORRO", "BUFANDA", "GUANTE",
]
POLERA_NORMALIZE = {
    "POLERA MANGA LARGA": "Polera ML", "POLERA ML": "Polera ML",
    "POLERA MANGA CORTA": "Polera MC", "POLERA MC": "Polera MC",
    "POLERA PIQUE": "Polera Piqué", "POLERON": "Poleron", "POLERA": "Polera",
    "CAMISA MANGA LARGA": "Camisa ML", "CAMISA ML": "Camisa ML",
    "CAMISA MANGA CORTA": "Camisa MC", "CAMISA MC": "Camisa MC",
    "CAMISA": "Camisa", "PARKA ML": "Parka", "PARKA MC": "Parka", "PARKA": "Parka",
}
GENEROS = ["NIÑA", "NIÑO", "HOMBRE", "MUJER", "UNISEX"]

def extraer_marca(nombre, sku=""):
    n, s = norm(nombre), norm(sku)
    for marca in MARCAS:
        mn = norm(marca)
        if mn in n or mn in s:
            return "Panama Jack" if marca == "PJACK" else marca.title().replace(" S ", " s ")
    return "Sin marca"

def extraer_linea_categoria(nombre, sku=""):
    n, s = norm(nombre), norm(sku)
    if "SEGURIDAD" in n or "SEGURIDAD" in s:
        return "Seguridad", "Calzado"
    for linea in LINEAS_CALZADO:
        if norm(linea) in n:
            return linea.title(), "Calzado"
    for linea in LINEAS_ROPA:
        if norm(linea) in n:
            return POLERA_NORMALIZE.get(linea, linea.title()), "Ropa"
    for linea in LINEAS_BAGS:
        if norm(linea) in n:
            return linea.title(), "Bags"
    for linea in LINEAS_ACCESORIOS:
        if norm(linea) in n:
            return linea.title(), "Accesorios"
    return "Sin línea", "Sin categoría"

def extraer_genero(nombre):
    n = norm(nombre)
    for genero in GENEROS:
        if norm(genero) in n:
            return genero.title()
    return "Sin género"

# ── API ───────────────────────────────────────────────────────────────────────
def sign_request(params):
    sorted_params = sorted(params.items())
    query_string  = urllib.parse.urlencode(sorted_params)
    return hmac.new(API_KEY.encode(), query_string.encode(), hashlib.sha256).hexdigest()

def call_api(action, extra_params={}):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    params = {
        "Action": action, "Format": "JSON", "Timestamp": timestamp,
        "UserID": USER_ID, "Version": "1.0", **extra_params,
    }
    params["Signature"] = sign_request(params)
    for intento in range(3):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if intento < 2:
                import time; time.sleep(5)
                continue
            print(f"ERROR {action}: {e}")
            return None

def get_orders(created_after, created_before=None):
    params = {"CreatedAfter": created_after, "Limit": 100, "Offset": 0,
              "ShippingType": "Fulfillment"}
    if created_before:
        params["CreatedBefore"] = created_before
    all_orders = []
    while True:
        data = call_api("GetOrders", params)
        if not data:
            break
        orders = (data.get("SuccessResponse", {})
                     .get("Body", {})
                     .get("Orders", {})
                     .get("Order", []))
        if isinstance(orders, dict):
            orders = [orders]
        if not orders:
            break
        all_orders.extend(orders)
        print(f"  Órdenes obtenidas: {len(all_orders)}")
        if len(orders) < 100:
            break
        params["Offset"] += 100
    return all_orders

def get_order_items(order_id):
    data = call_api("GetOrderItems", {"OrderId": order_id})
    if not data:
        return []
    items = (data.get("SuccessResponse", {})
                 .get("Body", {})
                 .get("OrderItems", {})
                 .get("OrderItem", []))
    if isinstance(items, dict):
        items = [items]
    return items

def procesar_ordenes(orders):
    rows = []
    for i, order in enumerate(orders):
        order_id   = order.get("OrderId", "")
        created_at = order.get("CreatedAt", "")
        status     = order.get("Statuses", {}).get("Status", "")
        if isinstance(status, list):
            status = status[0]

        items = get_order_items(order_id)
        for item in items:
            shipping_raw = (item.get("ShippingType", "") or "").strip()
            if shipping_raw != "Fulfillment":
                continue

            sku    = item.get("SellerSku", "")
            nombre = item.get("Name", "")
            price  = float(item.get("PaidPrice", 0) or 0)
            qty    = int(item.get("QtyOrdered", 1) or 1)

            linea, categoria = extraer_linea_categoria(nombre, sku)
            rows.append({
                "order_id":   order_id,
                "created_at": created_at,
                "status":     status,
                "sku":        sku,
                "sku15":      sku[:-3] if len(sku) > 3 else sku,
                "modelo":     sku[:7] if len(sku) >= 7 else sku,
                "nombre":     nombre,
                "marca":      extraer_marca(nombre, sku),
                "linea":      linea,
                "categoria":  categoria,
                "genero":     extraer_genero(nombre),
                "price":      price,
                "qty":        qty,
            })
        if (i + 1) % 20 == 0:
            print(f"  Procesadas {i+1}/{len(orders)} órdenes…")
    return rows

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    # Determinar desde cuándo buscar
    if os.path.exists(CSV_PATH):
        df_existing = pd.read_csv(CSV_PATH)
        if not df_existing.empty and "created_at" in df_existing.columns:
            last_date = pd.to_datetime(df_existing["created_at"]).max()
            # Retroceder 2 horas para no perder órdenes en el borde
            from datetime import timedelta
            since = (last_date - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
            print(f"CSV existente. Buscando órdenes desde {since}")
        else:
            since = FECHA_INICIO
            print(f"CSV vacío. Descarga completa desde {FECHA_INICIO}")
    else:
        since = FECHA_INICIO
        df_existing = pd.DataFrame()
        print(f"Sin CSV. Descarga completa desde {FECHA_INICIO}")

    # Bajar órdenes nuevas
    print(f"Bajando órdenes FBF desde {since}…")
    orders = get_orders(since, now_str)
    print(f"Total órdenes encontradas: {len(orders)}")

    if not orders:
        print("Sin órdenes nuevas. CSV sin cambios.")
        return

    # Procesar
    print("Procesando ítems…")
    new_rows = procesar_ordenes(orders)
    print(f"Ítems FBF nuevos: {len(new_rows)}")

    if not new_rows:
        print("Sin ítems FBF nuevos.")
        return

    df_new = pd.DataFrame(new_rows)

    # Combinar con existente y deduplicar
    if not df_existing.empty:
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
        df_combined.drop_duplicates(
            subset=["order_id", "sku"], keep="last", inplace=True
        )
    else:
        df_combined = df_new

    df_combined.sort_values("created_at", inplace=True)
    df_combined.to_csv(CSV_PATH, index=False)
    print(f"✅ CSV actualizado: {len(df_combined)} filas totales.")

if __name__ == "__main__":
    main()
