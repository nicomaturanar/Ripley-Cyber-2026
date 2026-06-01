import streamlit as st
import requests
from datetime import datetime, timedelta, date, timezone
import pandas as pd
import time
import unicodedata

st.set_page_config(
    page_title="Ripley Marketplace — Cyber Dashboard",
    page_icon="🛍️",
    layout="wide",
)

API_KEY  = st.secrets["RIPLEY_API_KEY"]
BASE_URL = "https://ripley-prod.mirakl.net/api"

def get_headers():
    return {"Authorization": API_KEY, "Accept": "application/json"}

# ── Normalización ─────────────────────────────────────────────────────────────
def normalizar(texto):
    texto = texto.upper()
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")

# ── Marcas ────────────────────────────────────────────────────────────────────
MARCAS = [
    "PANAMA JACK", "16 HRS", "BRUNO ROSSI", "ZAPPA", "POLLINI",
    "DAKOTA", "ENDURO", "IBIZAS HERITAGE", "LUZ DA LUA", "MINGO",
    "SHERPAS", "SHERPA S", "PLUMA",
]
SKU_PREFIJOS = {
    "PJ":  "Panama Jack",
    "PO":  "Pollini",
    "16H": "16 Hrs",
    "BR":  "Bruno Rossi",
}

def extract_brand(description: str, sku: str = "") -> str:
    nombre_norm = normalizar(description) if description else ""
    for marca in MARCAS:
        if normalizar(marca) in nombre_norm:
            return "Sherpas" if "SHERPA" in normalizar(marca) else marca.title()
    sku_up = (sku or "").upper()
    for prefijo, marca in SKU_PREFIJOS.items():
        if sku_up.startswith(prefijo):
            return marca
    return "Sin marca"

# ── Línea y Categoría ─────────────────────────────────────────────────────────
LINEAS_CALZADO = [
    "FLIP FLOP", "BALLERINA", "PANTUFLA", "ZAPATILLA", "SANDALIA",
    "MAFALDA", "MOCASIN", "ZAPATO", "BOTIN", "BOTA", "ALPARGATA",
]
LINEAS_ROPA = [
    "CAMISA MC", "CAMISA ML", "POLERA MC", "POLERA ML", "POLERA PIQUE",
    "PARKA ML", "TRAJE DE BANO",
    "BERMUDA", "BUZO", "CAMISA", "CHAQUETA", "CORTAVIENTO", "GORRO",
    "JEANS", "JOCKEY", "JOGGER", "PANTALON", "PARKA", "POLAR",
    "POLERON", "SHORT",
]
LINEAS_BAGS = [
    "BACKPACK", "BANANO", "BANDANAS", "BANDOLERA", "BELTBAG", "BILLETERAS",
    "BOLSO", "BOWLING", "CALCETIN", "CARTERAS", "CHARMS", "CINTURONES",
    "CINTURON", "CLASICAS", "CLUTCH", "CROSSBODY", "ESTUCHES", "FIESTA",
    "LLAVERO", "MOCHILA", "PANUELOS", "STRAPS", "TOTE",
]
GENEROS = ["NINA", "NINO", "HOMBRE", "MUJER", "UNISEX"]

def extraer_linea_y_categoria(nombre, sku):
    n = normalizar(nombre)
    s = normalizar(sku)

    if "SEGURIDAD" in n or "SEGURIDAD" in s:
        return "Seguridad", "Calzado"

    for linea in LINEAS_ROPA:
        if normalizar(linea) in n:
            return linea.title(), "Ropa"

    for linea in LINEAS_BAGS:
        if normalizar(linea) in n:
            return linea.title(), "Bags & Accesorios"

    for linea in LINEAS_CALZADO:
        if normalizar(linea) in n:
            return linea.title(), "Calzado"

    return "Sin línea", "No identificado"

def extraer_genero(nombre):
    n = normalizar(nombre)
    if "CARTERA" in n:
        return "Mujer"
    for genero in GENEROS:
        if normalizar(genero) in n:
            return genero.title()
    return "Sin género"

def normalizar_categoria_api(cat):
    cat_norm = normalizar(cat) if cat else ""
    if "ZAPATILLA" in cat_norm:
        return "Zapatilla"
    return cat.strip() if cat else ""

# ── API ───────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_orders(date_str: str) -> list:
    start_dt = f"{date_str}T04:00:00+00:00"
    next_day  = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
    end_dt    = f"{next_day}T03:59:59+00:00"

    all_orders = []
    offset = 0
    limit  = 100
    while True:
        params = {"start_date": start_dt, "end_date": end_dt, "max": limit, "offset": offset}
        try:
            r = requests.get(f"{BASE_URL}/orders", headers=get_headers(), params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            st.error(f"Error API: {e}")
            break
        orders = data.get("orders", [])
        all_orders.extend(orders)
        total  = data.get("total_count", 0)
        offset += limit
        if offset >= total or len(orders) == 0:
            break
    return all_orders

def parse_orders(orders: list) -> pd.DataFrame:
    rows = []
    for o in orders:
        created_raw = o.get("created_date", "")
        try:
            created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            created_dt = created_dt.astimezone(timezone(timedelta(hours=-4)))
        except Exception:
            created_dt = None

        for line in o.get("order_lines", []):
            desc    = line.get("description", "") or ""
            sku     = line.get("offer_sku", "") or ""
            product = line.get("product_title", "") or ""
            linea, categoria = extraer_linea_y_categoria(product, sku)

            rows.append({
                "order_id":   o.get("order_id", ""),
                "created_at": created_dt,
                "status":     o.get("order_state", ""),
                "price":      float(line.get("price", 0) or 0),
                "quantity":   int(line.get("quantity", 1) or 1),
                "sku":        sku,
                "sku15":      sku[:-3] if len(sku) > 3 else sku,
                "product":    product,
                "category":   categoria,
                "linea":      linea,
                "genero":     extraer_genero(product),
                "brand":      extract_brand(desc, sku),
            })

    if not rows:
        return pd.DataFrame(columns=["order_id","created_at","status","price","quantity","sku","sku15","product","category","linea","genero","brand"])

    df = pd.DataFrame(rows)
    df["hour_label"] = df["created_at"].apply(lambda x: f"{x.hour:02d}:00" if x is not None else None)
    return df

# ═══════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════
st.title("🛍️ Ripley Marketplace — Cyber Dashboard")
st.caption("Datos en tiempo real vía API Mercado Ripley (Mirakl)")

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuración")
    selected_date = st.date_input(
        "Fecha a analizar (hora Chile)",
        value=datetime.now(timezone(timedelta(hours=-4))).date(),
        max_value=datetime.now(timezone(timedelta(hours=-4))).date(),
    )
    auto_refresh = st.toggle("Auto-refresh (10 min)", value=False)
    if st.button("🔄 Refrescar ahora"):
        st.cache_data.clear()
        st.rerun()

date_str = selected_date.strftime("%Y-%m-%d")

with st.spinner("Cargando órdenes desde Ripley..."):
    orders_raw = get_orders(date_str)

if not orders_raw:
    st.warning("No se encontraron órdenes para la fecha seleccionada.")
    st.stop()

df_all = parse_orders(orders_raw)

# ── Filtros ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.header("🔎 Filtros")

    marcas_opts = sorted(df_all["brand"].dropna().unique().tolist())
    cats_opts   = sorted(df_all["category"].dropna().unique().tolist())
    lineas_opts = sorted(df_all["linea"].dropna().unique().tolist())
    generos_opts= sorted(df_all["genero"].dropna().unique().tolist())

    sel_marca  = st.multiselect("Marca",     marcas_opts)
    sel_cat    = st.multiselect("Categoría", cats_opts)
    sel_linea  = st.multiselect("Línea",     lineas_opts)
    sel_genero = st.multiselect("Género",    generos_opts)

df = df_all.copy()
if sel_marca:  df = df[df["brand"].isin(sel_marca)]
if sel_cat:    df = df[df["category"].isin(sel_cat)]
if sel_linea:  df = df[df["linea"].isin(sel_linea)]
if sel_genero: df = df[df["genero"].isin(sel_genero)]

if df.empty:
    st.warning("Sin resultados para los filtros seleccionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
total_orders = df["order_id"].nunique()
total_gmv    = df["price"].sum()
total_units  = df["quantity"].sum()
avg_ticket   = total_gmv / total_orders if total_orders else 0

st.subheader(f"📊 Resumen del {date_str} (hora Chile)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🛒 Órdenes",         f"{total_orders:,}")
c2.metric("💰 GMV",             f"${total_gmv:,.0f}")
c3.metric("📦 Unidades",        f"{total_units:,}")
c4.metric("🎯 Ticket promedio", f"${avg_ticket:,.0f}")

st.divider()

# ── Hora a hora ───────────────────────────────────────────────────────────────
st.subheader("🕐 Evolución hora a hora")
horas = [f"{h:02d}:00" for h in range(24)]
hourly = (
    df.groupby("hour_label")
    .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
    .reset_index()
)
hourly_table = (
    hourly[["hour_label","ordenes","gmv","unidades"]]
    .set_index("hour_label").reindex(horas, fill_value=0).reset_index()
)
hourly_table.columns = ["Hora","Órdenes","GMV","Unidades"]
now_chile = datetime.now(timezone(timedelta(hours=-4)))
if date_str == now_chile.strftime("%Y-%m-%d"):
    hourly_table = hourly_table.iloc[: now_chile.hour + 1]

display_h = hourly_table.copy()
display_h["GMV"] = display_h["GMV"].apply(lambda x: f"${x:,.0f}")
st.dataframe(display_h, use_container_width=True, hide_index=True)

col_g1, col_g2 = st.columns(2)
with col_g1:
    st.markdown("**GMV por hora**")
    st.bar_chart(hourly_table.set_index("Hora")["GMV"])
with col_g2:
    st.markdown("**Órdenes por hora**")
    st.bar_chart(hourly_table.set_index("Hora")["Órdenes"])

st.divider()

# ── Categoría ─────────────────────────────────────────────────────────────────
st.subheader("📂 Performance por Categoría")
cat = (
    df.groupby("category")
    .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
    .sort_values("gmv", ascending=False).reset_index()
)
cat.columns = ["Categoría","Órdenes","GMV","Unidades"]
cat_d = cat.copy(); cat_d["GMV"] = cat_d["GMV"].apply(lambda x: f"${x:,.0f}")
col1, col2 = st.columns([1,2])
with col1: st.dataframe(cat_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(cat.set_index("Categoría")["GMV"])

st.divider()

# ── Línea ─────────────────────────────────────────────────────────────────────
st.subheader("📋 Performance por Línea")
lin = (
    df.groupby("linea")
    .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
    .sort_values("gmv", ascending=False).head(15).reset_index()
)
lin.columns = ["Línea","Órdenes","GMV","Unidades"]
lin_d = lin.copy(); lin_d["GMV"] = lin_d["GMV"].apply(lambda x: f"${x:,.0f}")
col1, col2 = st.columns([1,2])
with col1: st.dataframe(lin_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(lin.set_index("Línea")["GMV"])

st.divider()

# ── Marca ─────────────────────────────────────────────────────────────────────
st.subheader("🏷️ Performance por Marca")
brand = (
    df.groupby("brand")
    .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
    .sort_values("gmv", ascending=False).head(10).reset_index()
)
brand.columns = ["Marca","Órdenes","GMV","Unidades"]
brand_d = brand.copy(); brand_d["GMV"] = brand_d["GMV"].apply(lambda x: f"${x:,.0f}")
col1, col2 = st.columns([1,2])
with col1: st.dataframe(brand_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(brand.set_index("Marca")["GMV"])

st.divider()

# ── Estado ────────────────────────────────────────────────────────────────────
st.subheader("📊 Distribución por estado")
status_counts = df.groupby("status")["order_id"].nunique().reset_index()
status_counts.columns = ["Estado","Órdenes"]
col_e, col_f = st.columns([1,2])
with col_e: st.dataframe(status_counts, use_container_width=True, hide_index=True)
with col_f: st.bar_chart(status_counts.set_index("Estado")["Órdenes"])

st.divider()

# ── SKU 15 ────────────────────────────────────────────────────────────────────
st.subheader("📋 Detalle por SKU 15")
sku15_df = (
    df.groupby("sku15")
    .agg(
        producto  = ("product",  "first"),
        categoria = ("category", "first"),
        linea     = ("linea",    "first"),
        marca     = ("brand",    "first"),
        genero    = ("genero",   "first"),
        ordenes   = ("order_id", "nunique"),
        unidades  = ("quantity", "sum"),
        gmv       = ("price",    "sum"),
    )
    .reset_index()
    .sort_values("gmv", ascending=False)
)
sku15_df.columns = ["SKU 15","Producto","Categoría","Línea","Marca","Género","Órdenes","Unidades","GMV"]
sku15_d = sku15_df.copy()
sku15_d["GMV"] = sku15_d["GMV"].apply(lambda x: f"${x:,.0f}")
st.dataframe(sku15_d, use_container_width=True, hide_index=True)

csv = sku15_df.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Descargar CSV", csv, "ordenes_ripley_sku15.csv", "text/csv")

if auto_refresh:
    time.sleep(600)
    st.rerun()
