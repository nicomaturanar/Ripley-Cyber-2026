import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd
import time

# ─── Configuración de página ───────────────────────────────────────────────
st.set_page_config(
    page_title="Ripley Marketplace — Cyber Dashboard",
    page_icon="🛍️",
    layout="wide",
)

# ─── Credenciales desde Streamlit Secrets ──────────────────────────────────
API_KEY  = st.secrets["RIPLEY_API_KEY"]
BASE_URL = "https://ripley-prod.mirakl.net/api"

# ─── Headers de autenticación Mirakl ───────────────────────────────────────
def get_headers():
    return {
        "Authorization": API_KEY,
        "Accept": "application/json",
    }

# ─── Llamada genérica a la API ──────────────────────────────────────────────
def call_api(endpoint: str, params: dict = {}) -> dict | None:
    url = f"{BASE_URL}{endpoint}"
    try:
        response = requests.get(url, headers=get_headers(), params=params, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as e:
        st.error(f"Error HTTP {response.status_code}: {response.text}")
        return None
    except requests.exceptions.RequestException as e:
        st.error(f"Error al conectar con la API de Ripley: {e}")
        return None

# ─── Obtener órdenes ────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_orders(date_str: str) -> list:
    """Obtiene todas las órdenes del día seleccionado."""
    # Formato correcto para Mirakl: ISO 8601 con timezone
    start_dt = f"{date_str}T00:00:00+00:00"
    end_dt   = f"{date_str}T23:59:59+00:00"

    all_orders = []
    offset = 0
    limit  = 100

    while True:
        params = {
            "start_date":  start_dt,
            "end_date":    end_dt,
            "max":         limit,
            "offset":      offset,
            "sort":        "dateCreated",
            "dir":         "DESC",
        }
        data = call_api("/orders", params)
        if not data:
            break

        orders = data.get("orders", [])
        all_orders.extend(orders)

        total = data.get("total_count", 0)
        offset += limit
        if offset >= total or len(orders) == 0:
            break

    return all_orders

# ─── Parsear órdenes a DataFrame ────────────────────────────────────────────
def parse_orders(orders: list) -> pd.DataFrame:
    rows = []
    for o in orders:
        created_raw = o.get("created_date", "")
        try:
            created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except Exception:
            created_dt = None

        order_state = o.get("order_state", "")

        for line in o.get("order_lines", []):
            price    = float(line.get("price", 0) or 0)
            qty      = int(line.get("quantity", 1) or 1)

            rows.append({
                "order_id":    o.get("order_id", ""),
                "created_at":  created_dt,
                "status":      order_state,
                "price":       price,
                "quantity":    qty,
                "sku":         line.get("offer_sku", ""),
                "product":     line.get("product_title", ""),
                "category":    line.get("category_label", ""),
                "brand":       line.get("offer_state_code", ""),  # Mirakl no tiene brand directo
            })

    if not rows:
        return pd.DataFrame(columns=["order_id","created_at","status","price","quantity","sku","product","category","brand"])

    df = pd.DataFrame(rows)
    df["hour"] = df["created_at"].apply(lambda x: x.hour if x else None)
    return df

# ═══════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════

st.title("🛍️ Ripley Marketplace — Cyber Dashboard")
st.caption("Datos en tiempo real vía API Mercado Ripley (Mirakl)")

# ─── Sidebar ────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Configuración")
    selected_date = st.date_input(
        "Fecha a analizar",
        value=datetime.now(timezone.utc).date(),
        max_value=datetime.now(timezone.utc).date(),
    )
    auto_refresh = st.toggle("Auto-refresh (10 min)", value=False)
    if st.button("🔄 Refrescar ahora"):
        st.cache_data.clear()
        st.rerun()

date_str = selected_date.strftime("%Y-%m-%d")

# ─── Carga de datos ─────────────────────────────────────────────────────────
with st.spinner("Cargando órdenes desde Ripley..."):
    orders_raw = get_orders(date_str)

if not orders_raw:
    st.warning("No se encontraron órdenes para la fecha seleccionada.")
    st.stop()

df = parse_orders(orders_raw)

# ─── KPIs principales ───────────────────────────────────────────────────────
total_orders  = df["order_id"].nunique()
total_gmv     = df["price"].sum()
total_units   = df["quantity"].sum()
avg_ticket    = total_gmv / total_orders if total_orders else 0

st.subheader(f"📊 Resumen del {date_str}")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🛒 Órdenes",          f"{total_orders:,}")
c2.metric("💰 GMV",              f"${total_gmv:,.0f}")
c3.metric("📦 Unidades",         f"{total_units:,}")
c4.metric("🎯 Ticket promedio",  f"${avg_ticket:,.0f}")

st.divider()

# ─── Tabla hora a hora ───────────────────────────────────────────────────────
st.subheader("🕐 Evolución hora a hora")

horas = [f"{h:02d}:00" for h in range(24)]
df["hour_label"] = df["created_at"].apply(
    lambda x: f"{x.hour:02d}:00" if x is not None else None
)

hourly = (
    df.groupby("hour_label")
    .agg(ordenes=("order_id", "nunique"), gmv=("price", "sum"), unidades=("quantity", "sum"))
    .reset_index()
)

hourly_table = (
    hourly[["hour_label", "ordenes", "gmv", "unidades"]]
    .set_index("hour_label")
    .reindex(horas, fill_value=0)
    .reset_index()
)
hourly_table.columns = ["Hora", "Órdenes", "GMV", "Unidades"]
hourly_table["GMV"] = hourly_table["GMV"].apply(lambda x: f"${x:,.0f}")

# Mostrar solo hasta la hora actual si es hoy
now_hour = datetime.now(timezone.utc).hour
if date_str == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
    hourly_table = hourly_table.iloc[: now_hour + 1]

st.dataframe(hourly_table, use_container_width=True, hide_index=True)

# Gráfico hora a hora
hourly_chart = (
    df.groupby("hour_label")
    .agg(gmv=("price", "sum"), ordenes=("order_id", "nunique"))
    .reindex(horas, fill_value=0)
)
col_g1, col_g2 = st.columns(2)
with col_g1:
    st.markdown("**GMV por hora**")
    st.bar_chart(hourly_chart["gmv"])
with col_g2:
    st.markdown("**Órdenes por hora**")
    st.bar_chart(hourly_chart["ordenes"])

st.divider()

# ─── Performance por Categoría ───────────────────────────────────────────────
st.subheader("📂 Performance por Categoría")
if df["category"].notna().any() and (df["category"] != "").any():
    cat = (
        df.groupby("category")
        .agg(ordenes=("order_id", "nunique"), gmv=("price", "sum"), unidades=("quantity", "sum"))
        .sort_values("gmv", ascending=False)
        .head(10)
        .reset_index()
    )
    cat.columns = ["Categoría", "Órdenes", "GMV", "Unidades"]
    cat_display = cat.copy()
    cat_display["GMV"] = cat_display["GMV"].apply(lambda x: f"${x:,.0f}")
    col_c1, col_c2 = st.columns([1, 2])
    with col_c1:
        st.dataframe(cat_display, use_container_width=True, hide_index=True)
    with col_c2:
        st.bar_chart(cat.set_index("Categoría")["GMV"])
else:
    st.info("No hay datos de categoría disponibles para este período.")

st.divider()

# ─── Distribución por estado ─────────────────────────────────────────────────
st.subheader("📊 Distribución por estado de órdenes")
status_counts = df.groupby("status")["order_id"].nunique().reset_index()
status_counts.columns = ["Estado", "Órdenes"]
col_e, col_f = st.columns([1, 2])
with col_e:
    st.dataframe(status_counts, use_container_width=True, hide_index=True)
with col_f:
    st.bar_chart(status_counts.set_index("Estado")["Órdenes"])

st.divider()

# ─── Tabla detalle ────────────────────────────────────────────────────────────
st.subheader("📋 Detalle de órdenes")
df_display = df[["order_id", "created_at", "status", "price", "quantity", "product", "category"]].copy()
df_display.columns = ["Order ID", "Fecha creación", "Estado", "Precio", "Unidades", "Producto", "Categoría"]
df_display = df_display.sort_values("Fecha creación", ascending=False)
st.dataframe(df_display, use_container_width=True, hide_index=True)

csv = df_display.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Descargar CSV", csv, "ordenes_ripley_cyber.csv", "text/csv")

# ─── Auto-refresh ─────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(600)
    st.rerun()
