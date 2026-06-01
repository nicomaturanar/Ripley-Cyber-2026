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
    "BACKPACK", "BANANO", "BANDANAS", "BANDANA", "BANDOLERA", "BELTBAG", "BILLETERAS",
    "BOLSO", "BOWLING", "CALCETIN", "CARTERAS", "CHARMS", "CINTURONES",
    "CINTURON", "CLASICAS", "CLUTCH", "CROSSBODY", "ESTUCHES", "FIESTA",
    "LLAVERO", "MOCHILA", "PANUELOS", "STRAPS", "TOTE",
]
GENEROS = ["NINA", "NINO", "HOMBRE", "MUJER", "UNISEX"]

def extraer_linea_y_categoria(nombre, sku):
    n = normalizar(nombre)
    if "SEGURIDAD" in n or "SEGURIDAD" in normalizar(sku):
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

# ── Rango año anterior ────────────────────────────────────────────────────────
def get_rango_anio_anterior(date_str: str):
    """Retorna el mismo día ISO del año anterior, cortando a la hora actual si es hoy."""
    chile_tz = timezone(timedelta(hours=-4))
    ahora    = datetime.now(chile_tz)
    hoy_str  = ahora.strftime("%Y-%m-%d")

    fecha_actual = date.fromisoformat(date_str)
    iso_year_ant = fecha_actual.year - 1
    iso_week     = fecha_actual.isocalendar()[1]
    iso_day      = fecha_actual.isocalendar()[2]
    fecha_ant    = date.fromisocalendar(iso_year_ant, iso_week, iso_day)

    # Si estamos viendo hoy → cortar a la hora actual; si no → día completo
    if date_str == hoy_str:
        hora_corte = ahora.strftime("%H:%M:%S")
    else:
        hora_corte = "23:59:59"

    # 00:00 Chile = 04:00 UTC
    start_dt = f"{fecha_ant}T04:00:00+00:00"
    # hora_corte en Chile → sumar 4h para UTC, pero si pasa de medianoche UTC usar día siguiente
    from datetime import datetime as _dt
    hora_corte_dt  = _dt.strptime(hora_corte, "%H:%M:%S")
    hora_corte_utc = hora_corte_dt + timedelta(hours=4)
    if hora_corte_utc.day > 1:  # pasó medianoche UTC
        next_ant = (fecha_ant + timedelta(days=1)).isoformat()
        end_dt   = f"{next_ant}T{hora_corte_utc.strftime('%H:%M:%S')}+00:00"
    else:
        end_dt   = f"{fecha_ant}T{hora_corte_utc.strftime('%H:%M:%S')}+00:00"

    return start_dt, end_dt, fecha_ant, hora_corte

# ── API ───────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def get_orders(date_str: str) -> list:
    start_dt = f"{date_str}T04:00:00+00:00"
    next_day  = (date.fromisoformat(date_str) + timedelta(days=1)).isoformat()
    end_dt    = f"{next_day}T03:59:59+00:00"
    return _fetch_orders(start_dt, end_dt)

@st.cache_data(ttl=300)
def get_orders_anterior(date_str: str) -> list:
    start_dt, end_dt, _, _ = get_rango_anio_anterior(date_str)
    return _fetch_orders(start_dt, end_dt)

def _fetch_orders(start_dt: str, end_dt: str) -> list:
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
                "brand":      extract_brand(desc or product, sku),
            })

    if not rows:
        return pd.DataFrame(columns=["order_id","created_at","status","price","quantity","sku","sku15","product","category","linea","genero","brand"])

    df = pd.DataFrame(rows)
    df["hour_label"] = df["created_at"].apply(lambda x: f"{x.hour:02d}:00" if x else None)
    return df

# ── Helpers ───────────────────────────────────────────────────────────────────
def var_pct(actual, anterior):
    if anterior and anterior != 0:
        return (actual - anterior) / anterior
    return None

def fmt_var(v):
    if v is None:
        return "—"
    arrow = "▲" if v >= 0 else "▼"
    return f"{arrow} {abs(v)*100:.1f}%"

def tabla_performance(df_act, df_ant, col, titulo, emoji):
    """Genera tabla agrupada con variaciones vs año anterior."""
    act = (
        df_act.groupby(col)
        .agg(gmv_act=("price","sum"), uni_act=("quantity","sum"))
        .reset_index()
    )
    ant = (
        df_ant.groupby(col)
        .agg(gmv_ant=("price","sum"), uni_ant=("quantity","sum"))
        .reset_index()
    ) if df_ant is not None and not df_ant.empty else pd.DataFrame(columns=[col,"gmv_ant","uni_ant"])

    merged = act.merge(ant, on=col, how="left")
    merged["gmv_ant"]  = merged["gmv_ant"].fillna(0)
    merged["uni_ant"]  = merged["uni_ant"].fillna(0)
    merged["var_gmv"]  = merged.apply(lambda r: var_pct(r["gmv_act"], r["gmv_ant"]), axis=1)
    merged["var_uni"]  = merged.apply(lambda r: var_pct(r["uni_act"], r["uni_ant"]), axis=1)
    merged = merged.sort_values("gmv_act", ascending=False)

    total_gmv = merged["gmv_act"].sum()
    total_uni = merged["uni_act"].sum()
    merged["share_gmv"] = merged["gmv_act"] / total_gmv * 100 if total_gmv else 0
    merged["share_uni"] = merged["uni_act"] / total_uni * 100 if total_uni else 0

    display = merged[[col,"gmv_act","share_gmv","var_gmv","uni_act","share_uni","var_uni"]].copy()
    display.columns = [titulo, "GMV", "Share GMV", "Var% GMV", "Unidades", "Share Uni", "Var% Uni"]
    display["GMV"]       = display["GMV"].apply(lambda x: f"${x:,.0f}")
    display["Share GMV"] = display["Share GMV"].apply(lambda x: f"{x:.1f}%")
    display["Share Uni"] = display["Share Uni"].apply(lambda x: f"{x:.1f}%")
    display["Var% GMV"]  = display["Var% GMV"].apply(fmt_var)
    display["Var% Uni"]  = display["Var% Uni"].apply(fmt_var)

    return display, merged

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

# ── Carga de datos ────────────────────────────────────────────────────────────
col_spin1, col_spin2 = st.columns(2)
with col_spin1:
    with st.spinner("Cargando órdenes actuales..."):
        orders_raw = get_orders(date_str)
with col_spin2:
    with st.spinner("Cargando año anterior..."):
        orders_ant = get_orders_anterior(date_str)

if not orders_raw:
    st.warning("No se encontraron órdenes para la fecha seleccionada.")
    st.stop()

df_all = parse_orders(orders_raw)
df_ant = parse_orders(orders_ant) if orders_ant else pd.DataFrame()

# Info año anterior
_, _, fecha_ant, hora_corte = get_rango_anio_anterior(date_str)
st.caption(f"📅 Comparando vs {fecha_ant} hasta las {hora_corte[:5]} h (mismo día ISO año anterior)")

# ── Filtros ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.header("🔎 Filtros")
    marcas_opts  = sorted(df_all["brand"].dropna().unique().tolist())
    cats_opts    = sorted(df_all["category"].dropna().unique().tolist())
    lineas_opts  = sorted(df_all["linea"].dropna().unique().tolist())
    generos_opts = sorted(df_all["genero"].dropna().unique().tolist())

    sel_marca  = st.multiselect("Marca",     marcas_opts)
    sel_cat    = st.multiselect("Categoría", cats_opts)
    sel_linea  = st.multiselect("Línea",     lineas_opts)
    sel_genero = st.multiselect("Género",    generos_opts)

def aplicar_filtros(df):
    if sel_marca:  df = df[df["brand"].isin(sel_marca)]
    if sel_cat:    df = df[df["category"].isin(sel_cat)]
    if sel_linea:  df = df[df["linea"].isin(sel_linea)]
    if sel_genero: df = df[df["genero"].isin(sel_genero)]
    return df

df     = aplicar_filtros(df_all.copy())
df_ant = aplicar_filtros(df_ant.copy()) if not df_ant.empty else df_ant

if df.empty:
    st.warning("Sin resultados para los filtros seleccionados.")
    st.stop()

# ── KPIs ──────────────────────────────────────────────────────────────────────
total_orders = df["order_id"].nunique()
total_gmv    = df["price"].sum()
total_units  = df["quantity"].sum()
avg_ticket   = total_gmv / total_orders if total_orders else 0

gmv_ant  = df_ant["price"].sum()    if not df_ant.empty else 0
uni_ant  = df_ant["quantity"].sum() if not df_ant.empty else 0

st.subheader(f"📊 Resumen del {date_str} (hora Chile)")
c1, c2, c3, c4 = st.columns(4)
c1.metric("🛒 Órdenes",         f"{total_orders:,}")
c2.metric("💰 GMV",             f"${total_gmv:,.0f}",  fmt_var(var_pct(total_gmv,  gmv_ant)))
c3.metric("📦 Unidades",        f"{total_units:,}",    fmt_var(var_pct(total_units, uni_ant)))
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

# Año anterior hora a hora
if not df_ant.empty:
    hourly_ant = (
        df_ant.groupby("hour_label")
        .agg(gmv_ant=("price","sum"), ord_ant=("order_id","nunique"))
        .reset_index()
    )
    hourly_table = hourly_table.merge(hourly_ant, left_on="Hora", right_on="hour_label", how="left").drop(columns=["hour_label"])
    hourly_table["gmv_ant"] = hourly_table["gmv_ant"].fillna(0)
    hourly_table["Var% GMV"] = hourly_table.apply(lambda r: fmt_var(var_pct(r["GMV"], r["gmv_ant"])), axis=1)

total_gmv_h = hourly_table["GMV"].sum()
total_uni_h = hourly_table["Unidades"].sum()
hourly_table["GMV acum"] = hourly_table["GMV"].cumsum()
hourly_table["Share GMV"] = hourly_table["GMV"].apply(lambda x: f"{x/total_gmv_h*100:.1f}%" if total_gmv_h else "0%")
hourly_table["Share Uni"] = hourly_table["Unidades"].apply(lambda x: f"{x/total_uni_h*100:.1f}%" if total_uni_h else "0%")

display_h = hourly_table.copy()
cols_show = ["Hora","Órdenes","GMV","Share GMV","Unidades","Share Uni","GMV acum"]
if "Var% GMV" in display_h.columns:
    cols_show.append("Var% GMV")
display_h = display_h[cols_show]
display_h["GMV"]      = display_h["GMV"].apply(lambda x: f"${x:,.0f}")
display_h["GMV acum"] = display_h["GMV acum"].apply(lambda x: f"${x:,.0f}")
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
cat_d, _ = tabla_performance(df, df_ant, "category", "Categoría", "📂")
col1, col2 = st.columns([2,1])
with col1: st.dataframe(cat_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(df.groupby("category")["price"].sum().sort_values(ascending=False))

st.divider()

# ── Línea ─────────────────────────────────────────────────────────────────────
st.subheader("📋 Performance por Línea")
lin_d, _ = tabla_performance(df, df_ant, "linea", "Línea", "👟")
col1, col2 = st.columns([2,1])
with col1: st.dataframe(lin_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(df.groupby("linea")["price"].sum().sort_values(ascending=False).head(15))

st.divider()

# ── Marca ─────────────────────────────────────────────────────────────────────
st.subheader("🏷️ Performance por Marca")
brand_d, _ = tabla_performance(df, df_ant, "brand", "Marca", "🏷️")
col1, col2 = st.columns([2,1])
with col1: st.dataframe(brand_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(df.groupby("brand")["price"].sum().sort_values(ascending=False).head(10))

st.divider()

# ── Género ────────────────────────────────────────────────────────────────────
st.subheader("👤 Performance por Género")
gen_d, _ = tabla_performance(df, df_ant, "genero", "Género", "👤")
col1, col2 = st.columns([2,1])
with col1: st.dataframe(gen_d, use_container_width=True, hide_index=True)
with col2: st.bar_chart(df.groupby("genero")["price"].sum().sort_values(ascending=False))

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

sku15_act = (
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
)

total_gmv_sku = sku15_act["gmv"].sum()
total_uni_sku = sku15_act["unidades"].sum()
sku15_act["Share GMV"] = sku15_act["gmv"].apply(lambda x: f"{x/total_gmv_sku*100:.1f}%" if total_gmv_sku else "0%")
sku15_act["Share Uni"] = sku15_act["unidades"].apply(lambda x: f"{x/total_uni_sku*100:.1f}%" if total_uni_sku else "0%")

if not df_ant.empty:
    sku15_ant = (
        df_ant.groupby("sku15")
        .agg(uni_ant=("quantity","sum"), gmv_ant=("price","sum"))
        .reset_index()
    )
    sku15_act = sku15_act.merge(sku15_ant, on="sku15", how="left")
    sku15_act["gmv_ant"] = sku15_act["gmv_ant"].fillna(0)
    sku15_act["uni_ant"] = sku15_act["uni_ant"].fillna(0)
    sku15_act["Var% GMV"] = sku15_act.apply(lambda r: fmt_var(var_pct(r["gmv"], r["gmv_ant"])), axis=1)
    sku15_act["Var% Uni"] = sku15_act.apply(lambda r: fmt_var(var_pct(r["unidades"], r["uni_ant"])), axis=1)
    sku15_act = sku15_act.sort_values("gmv", ascending=False)
    sku15_d = sku15_act[["sku15","producto","categoria","linea","marca","genero","ordenes","unidades","Share Uni","Var% Uni","gmv","Share GMV","Var% GMV"]].copy()
    sku15_d.columns = ["SKU 15","Producto","Categoría","Línea","Marca","Género","Órdenes","Unidades","Share Uni","Var% Uni","GMV","Share GMV","Var% GMV"]
else:
    sku15_act = sku15_act.sort_values("gmv", ascending=False)
    sku15_d = sku15_act[["sku15","producto","categoria","linea","marca","genero","ordenes","unidades","Share Uni","gmv","Share GMV"]].copy()
    sku15_d.columns = ["SKU 15","Producto","Categoría","Línea","Marca","Género","Órdenes","Unidades","Share Uni","GMV","Share GMV"]

sku15_d["GMV"] = sku15_d["GMV"].apply(lambda x: f"${x:,.0f}")
st.dataframe(sku15_d, use_container_width=True, hide_index=True)

csv = sku15_act.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Descargar CSV", csv, "ordenes_ripley_sku15.csv", "text/csv")

if auto_refresh:
    time.sleep(600)
    st.rerun()
