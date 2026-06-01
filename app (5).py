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

API_KEY  = st.secrets["RIPLEY_API_KEY"]
BASE_URL = "https://ripley-prod.mirakl.net/api"

def get_headers():
    return {
        "Authorization": API_KEY,
        "Accept": "application/json",
    }

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

st.title("🛍️ Ripley Marketplace — Cyber Dashboard")
st.caption("Datos en tiempo real vía API Mercado Ripley (Mirakl)")

# ─── DEBUG: mostrar respuesta cruda de la API ────────────────────────────────
st.subheader("🔍 Debug — Respuesta cruda de la API")

# Intentar varias combinaciones de parámetros de fecha
test_params_list = [
    # Sin filtro de fecha — trae todo
    {"max": 5},
    # Con start_date solo
    {"start_date": f"{date_str}T00:00:00+00:00", "max": 5},
    # Con ambas fechas
    {"start_date": f"{date_str}T00:00:00+00:00", "end_date": f"{date_str}T23:59:59+00:00", "max": 5},
]

for i, params in enumerate(test_params_list):
    st.markdown(f"**Test {i+1}:** `{params}`")
    url = f"{BASE_URL}/orders"
    try:
        r = requests.get(url, headers=get_headers(), params=params, timeout=30)
        st.write(f"Status: {r.status_code}")
        try:
            data = r.json()
            total = data.get("total_count", "N/A")
            orders = data.get("orders", [])
            st.write(f"total_count: {total} | órdenes recibidas: {len(orders)}")
            if orders:
                st.write("Primer order (campos principales):")
                o = orders[0]
                st.json({
                    "order_id": o.get("order_id"),
                    "created_date": o.get("created_date"),
                    "order_state": o.get("order_state"),
                    "price": o.get("price"),
                    "order_lines_count": len(o.get("order_lines", [])),
                    "first_line_keys": list(o.get("order_lines", [{}])[0].keys()) if o.get("order_lines") else [],
                })
        except Exception as e:
            st.write(f"No JSON: {r.text[:500]}")
    except Exception as e:
        st.error(f"Error: {e}")
    st.divider()
