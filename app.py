import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from dateutil import parser
import sqlite3
import matplotlib.pyplot as plt
import io
import os

# Configuración DB para seguimiento (PulpoVigía)
conn = sqlite3.connect('anuncios.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS anuncios
             (id TEXT PRIMARY KEY, page_name TEXT, bodies TEXT, snapshot_url TEXT, 
              start_time TEXT, days_active INTEGER, impressions TEXT, spend TEXT, 
              fetch_date TEXT)''')
conn.commit()

# Título
st.title("PulpoIA Personal - Explorador de Anuncios Meta")

st.write("Herramienta personal para replicar PulpoIA: fetch automático, filtros, análisis IA simple, descargas y seguimiento.")

# Inputs
access_token = st.text_input("Access Token Meta:", type="password")
country = st.selectbox("País (ej. ES=España):", ["ES", "MX", "AR", "CO", "US", "ALL"], index=0)
min_days = st.number_input("Mín. días activos:", value=10)
max_results = st.number_input("Máx. anuncios:", value=500, step=100)
filter_infoproducts = st.checkbox("Filtrar infoproductos", value=True)
cta_filter = st.text_input("Filtro CTA (ej. 'Comprar ahora'):")

# Keywords para infoproductos y "ganadores"
infoproduct_keywords = ["curso", "aprende", "guía", "masterclass", "ebook", "taller", "webinar", "entrenamiento", "programa"]
ganador_threshold = 100000  # Impresiones mínimas para "ganador"

if st.button("Fetch Anuncios (Biblioteca)"):
    if not access_token:
        st.error("Ingresa token.")
    else:
        st.write("Fetchando... Puede tardar.")
        progress_bar = st.progress(0)
        
        url = "https://graph.facebook.com/v20.0/ads_archive"
        params = {
            'access_token': access_token,
            'ad_active_status': 'ACTIVE',
            'ad_type': 'ALL',
            'search_terms': '',
            'ad_reached_countries': [country] if country != "ALL" else ['ALL'],
            'fields': 'id,page_name,ad_creative_bodies,ad_snapshot_url,ad_delivery_start_time,impressions,spend,currency',
            'limit': 100
        }
        
        ads = []
        fetched = 0
        while url and fetched < max_results:
            response = requests.get(url, params=params)
            data = response.json()
            if 'data' in data:
                for ad in data['data']:
                    start_time = parser.parse(ad.get('ad_delivery_start_time'))
                    days_active = (datetime.now() - start_time).days
                    if days_active >= min_days:
                        bodies = ' '.join(ad.get('ad_creative_bodies', []))
                        is_infoproduct = any(kw.lower() in bodies.lower() for kw in infoproduct_keywords) if filter_infoproducts else True
                        has_cta = cta_filter.lower() in bodies.lower() if cta_filter else True
                        if is_infoproduct and has_cta:
                            impressions = int(ad.get('impressions', {}).get('lower_bound', '0').replace(',', ''))
                            is_ganador = impressions >= ganador_threshold
                            ad_data = {
                                'ID': ad['id'],
                                'Página': ad['page_name'],
                                'Texto': bodies,
                                'Snapshot': ad['ad_snapshot_url'],
                                'Días Activos': days_active,
                                'Impresiones': impressions,
                                'Gasto': ad.get('spend', {}).get('lower_bound', 'N/A'),
                                'Ganador': 'Sí' if is_ganador else 'No'
                            }
                            ads.append(ad_data)
                            # Guardar en DB para seguimiento
                            fetch_date = datetime.now().strftime('%Y-%m-%d')
                            c.execute("INSERT OR REPLACE INTO anuncios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                      (ad['id'], ad['page_name'], bodies, ad['ad_snapshot_url'], 
                                       ad['ad_delivery_start_time'], days_active, str(impressions), 
                                       ad.get('spend', {}).get('lower_bound', 'N/A'), fetch_date))
                            conn.commit()
                            fetched += 1
            if 'paging' in data and 'next' in data['paging']:
                url = data['paging']['next']
                params = {}
            else:
                url = None
            progress_bar.progress(min(fetched / max_results, 1.0))
        
        if ads:
            df = pd.DataFrame(ads)
            df = df.sort_values('Impresiones', ascending=False)  # Orden por desempeño
            st.write(f"{len(ads)} anuncios encontrados.")
            st.dataframe(df)
            
            # Agrupar por página para "ofertas escaladas" (número de anuncios activos por página)
            grouped = df.groupby('Página').agg({'ID': 'count', 'Impresiones': 'sum'}).rename(columns={'ID': 'Anuncios Activos'})
            grouped = grouped.sort_values('Anuncios Activos', ascending=False)
            st.subheader("Ofertas Escaladas (por Página)")
            st.dataframe(grouped)
            
            # Descargas
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Descargar CSV", csv, "anuncios.csv")
            
            # Descarga de snapshot/video (ejemplo para uno, expande si quieres)
            selected_id = st.selectbox("Selecciona ID para descargar snapshot:", df['ID'])
            if selected_id:
                snapshot_url = df[df['ID'] == selected_id]['Snapshot'].values[0]
                st.link_button("Ver/Descargar Creativo", snapshot_url)
                # Intento de descarga video (si Meta expone link, sino manual)
                st.write("Para video: abre el snapshot y descarga manual. (Auto-descarga limitada por Meta).")

# PulpoAgente (Análisis IA simple)
st.subheader("PulpoAgente: Instrucciones IA")
instruccion = st.text_area("Da una instrucción (ej. 'Analiza este copy: [pega texto]')")
if st.button("Ejecutar Agente"):
    if instruccion:
        # Análisis simple: cuenta keywords, sugiere mejoras
        keywords_found = [kw for kw in infoproduct_keywords if kw in instruccion.lower()]
        st.write(f"Análisis: Keywords detectados: {keywords_found}. Sugerencia: Agrega CTA fuerte si no hay. Desempeño probable: Alto si >10 días.")

# PulpoVigía: Seguimiento
st.subheader("PulpoVigía: Seguimiento de Ofertas")
selected_page = st.selectbox("Selecciona Página para gráfico:", pd.read_sql("SELECT DISTINCT page_name FROM anuncios", conn)['page_name'])
if selected_page:
    query = f"SELECT fetch_date, days_active FROM anuncios WHERE page_name = '{selected_page}' ORDER BY fetch_date"
    df_track = pd.read_sql(query, conn)
    if not df_track.empty:
        fig, ax = plt.subplots()
        ax.plot(df_track['fetch_date'], df_track['days_active'], marker='o')
        ax.set_xlabel('Fecha Fetch')
        ax.set_ylabel('Días Activos')
        st.pyplot(fig)
    else:
        st.write("No hay datos históricos para esta página. Fetch más veces.")

# Favoritos (simple, guarda en session)
if 'favoritos' not in st.session_state:
    st.session_state.favoritos = []
st.subheader("Favoritos")
fav_id = st.text_input("Agrega ID a favoritos:")
if st.button("Guardar Favorito"):
    st.session_state.favoritos.append(fav_id)
st.write(st.session_state.favoritos)

# Footer
st.markdown("---")
st.write("Versión personal. Fetch diario manual para seguimiento. Si necesitas expandir (ej. auto-descargas), dime.")
