# 🛍️ Gino S.A — Ripley Cyber Dashboard

Dashboard en tiempo real para seguimiento de ventas en Ripley Marketplace durante el Cyber.

## ¿Qué muestra?
- Total de órdenes, GMV, unidades vendidas y ticket promedio
- Tabla y gráfico de órdenes y GMV hora a hora
- Performance por categoría (top 10)
- Performance por marca (top 10)
- Distribución por estado de órdenes
- Tabla detalle con exportación a CSV
- Auto-refresh cada 10 minutos (opcional)

## Despliegue en Streamlit Cloud

1. Sube este repo a GitHub (puede ser privado)
2. Ve a [share.streamlit.io](https://share.streamlit.io) y conecta tu cuenta GitHub
3. Selecciona este repositorio y el archivo `app.py`
4. En **Advanced settings → Secrets**, pega esto:

```toml
RIPLEY_API_KEY = "8f661bf3-39da-4eec-b42b-d8ca8529555f"
```

5. Haz click en **Deploy** — en ~2 minutos tendrás tu link público.

## Ejecución local

```bash
pip install -r requirements.txt
# Crea el archivo .streamlit/secrets.toml con tu API key
streamlit run app.py
```

## Diferencias con Falabella
- Ripley usa la plataforma **Mirakl** (no Seller Center)
- La autenticación es más simple: solo un header `Authorization: <API_KEY>`
- No requiere firma SHA256
- Endpoint base: `https://ripley-prod.mirakl.net/api`
