import streamlit as st
import requests
from datetime import datetime, timedelta, timezone
import pandas as pd
import time

st.set_page_config(
    page_title="Ripley Marketplace — Cyber Dashboard",
    page_icon="🛍️",
    layout="wide",
)

API_KEY  = st.secrets["RIPLEY_API_KEY"]
BASE_URL = "https://ripley-prod.mirakl.net/api"

def get_headers():
    return {"Authorization": API_KEY, "Accept": "application/json"}

@st.cache_data(ttl=300)
def get_orders(date_str: str) -> list:
    # Chile es UTC-4, así que un día local = desde las 04:00 UTC hasta las 04:00 UTC del día siguiente
    start_dt = f"{date_str}T04:00:00+00:00"
    # Día siguiente a las 03:59:59 UTC
    from datetime import date
    d = date.fromisoformat(date_str)
    next_day = (d + timedelta(days=1)).isoformat()
    end_dt = f"{next_day}T03:59:59+00:00"

    all_orders = []
    offset = 0
    limit  = 100

    while True:
        params = {
            "start_date": start_dt,
            "end_date":   end_dt,
            "max":        limit,
            "offset":     offset,
        }
        url = f"{BASE_URL}/orders"
        try:
            r = requests.get(url, headers=get_headers(), params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            st.error(f"Error API: {e}")
            break

        orders = data.get("orders", [])
        all_orders.extend(orders)
        total = data.get("total_count", 0)
        offset += limit
        if offset >= total or len(orders) == 0:
            break

    return all_orders

def extract_brand(description: str) -> str:
    """Extrae la marca del campo description (suele ser la primera palabra o segmento)."""
    if not description:
        return ""
    # Description suele venir como "MARCA Modelo descripción..." — tomamos primera palabra
    return description.split()[0].title() if description.strip() else ""

def parse_orders(orders: list) -> pd.DataFrame:
    rows = []
    for o in orders:
        created_raw = o.get("created_date", "")
        try:
            created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            # Convertir a hora Chile (UTC-4)
            created_dt = created_dt.astimezone(timezone(timedelta(hours=-4)))
        except Exception:
            created_dt = None

        order_state = o.get("order_state", "")

        for line in o.get("order_lines", []):
            price = float(line.get("price", 0) or 0)
            qty   = int(line.get("quantity", 1) or 1)
            desc  = line.get("description", "") or ""

            rows.append({
                "order_id":   o.get("order_id", ""),
                "created_at": created_dt,
                "status":     order_state,
                "price":      price,
                "quantity":   qty,
                "sku":        line.get("offer_sku", ""),
                "product":    line.get("product_title", ""),
                "category":   line.get("category_label", ""),
                "brand":      extract_brand(desc),
            })

    if not rows:
        return pd.DataFrame(columns=["order_id","created_at","status","price","quantity","sku","product","category","brand"])

    df = pd.DataFrame(rows)
    df["hour_label"] = df["created_at"].apply(lambda x: f"{x.hour:02d}:00" if x is not None else None)
    return df

# ═══════════════════════════════════════════════════════════════════════════
#  UI
# ═══════════════════════════════════════════════════════════════════════════
st.title("🛍️ Ripley Marketplace — Cyber Dashboard")
st.caption("Datos en tiempo real vía API Mercado Ripley (Mirakl)")

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

df = parse_orders(orders_raw)

# ─── KPIs ───────────────────────────────────────────────────────────────────
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

# ─── Tabla hora a hora ───────────────────────────────────────────────────────
st.subheader("🕐 Evolución hora a hora")
horas = [f"{h:02d}:00" for h in range(24)]

hourly = (
    df.groupby("hour_label")
    .agg(ordenes=("order_id", "nunique"), gmv=("price", "sum"), unidades=("quantity", "sum"))
    .reset_index()
)
hourly_table = (
    hourly[["hour_label", "ordenes", "gmv", "unidades"]]
    .set_index("hour_label").reindex(horas, fill_value=0).reset_index()
)
hourly_table.columns = ["Hora", "Órdenes", "GMV", "Unidades"]

now_chile = datetime.now(timezone(timedelta(hours=-4)))
if date_str == now_chile.strftime("%Y-%m-%d"):
    hourly_table = hourly_table.iloc[: now_chile.hour + 1]

display_table = hourly_table.copy()
display_table["GMV"] = display_table["GMV"].apply(lambda x: f"${x:,.0f}")
st.dataframe(display_table, use_container_width=True, hide_index=True)

col_g1, col_g2 = st.columns(2)
with col_g1:
    st.markdown("**GMV por hora**")
    st.bar_chart(hourly_table.set_index("Hora")["GMV"])
with col_g2:
    st.markdown("**Órdenes por hora**")
    st.bar_chart(hourly_table.set_index("Hora")["Órdenes"])

st.divider()

# ─── Categoría ───────────────────────────────────────────────────────────────
st.subheader("📂 Performance por Categoría")
if df["category"].notna().any() and (df["category"] != "").any():
    cat = (
        df.groupby("category")
        .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
        .sort_values("gmv", ascending=False).head(10).reset_index()
    )
    cat.columns = ["Categoría","Órdenes","GMV","Unidades"]
    cat_disp = cat.copy()
    cat_disp["GMV"] = cat_disp["GMV"].apply(lambda x: f"${x:,.0f}")
    col_c1, col_c2 = st.columns([1,2])
    with col_c1:
        st.dataframe(cat_disp, use_container_width=True, hide_index=True)
    with col_c2:
        st.bar_chart(cat.set_index("Categoría")["GMV"])
else:
    st.info("Sin datos de categoría.")

st.divider()

# ─── Marca ────────────────────────────────────────────────────────────────────
st.subheader("🏷️ Performance por Marca")
if df["brand"].notna().any() and (df["brand"] != "").any():
    brand = (
        df.groupby("brand")
        .agg(ordenes=("order_id","nunique"), gmv=("price","sum"), unidades=("quantity","sum"))
        .sort_values("gmv", ascending=False).head(10).reset_index()
    )
    brand.columns = ["Marca","Órdenes","GMV","Unidades"]
    brand_disp = brand.copy()
    brand_disp["GMV"] = brand_disp["GMV"].apply(lambda x: f"${x:,.0f}")
    col_b1, col_b2 = st.columns([1,2])
    with col_b1:
        st.dataframe(brand_disp, use_container_width=True, hide_index=True)
    with col_b2:
        st.bar_chart(brand.set_index("Marca")["GMV"])
else:
    st.info("Sin datos de marca.")

st.divider()

# ─── Estados ─────────────────────────────────────────────────────────────────
st.subheader("📊 Distribución por estado")
status_counts = df.groupby("status")["order_id"].nunique().reset_index()
status_counts.columns = ["Estado","Órdenes"]
col_e, col_f = st.columns([1,2])
with col_e:
    st.dataframe(status_counts, use_container_width=True, hide_index=True)
with col_f:
    st.bar_chart(status_counts.set_index("Estado")["Órdenes"])

st.divider()

# ─── Detalle ──────────────────────────────────────────────────────────────────
st.subheader("📋 Detalle de órdenes")
df_display = df[["order_id","created_at","status","price","quantity","sku","product","category","brand"]].copy()
df_display.columns = ["Order ID","Fecha creación","Estado","Precio","Unidades","SKU","Producto","Categoría","Marca"]
df_display = df_display.sort_values("Fecha creación", ascending=False)
st.dataframe(df_display, use_container_width=True, hide_index=True)

csv = df_display.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Descargar CSV", csv, "ordenes_ripley_cyber.csv", "text/csv")

if auto_refresh:
    time.sleep(600)
    st.rerun()
