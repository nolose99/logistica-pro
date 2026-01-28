import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import time
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from openlocationcode import openlocationcode as olc
import io # Para poder descargar el Excel

# --- 1. CONFIGURACIÓN DE LA PÁGINA (MODO PRO) ---
st.set_page_config(
    page_title="LOGÍSTICA 360 | ARAGÓN", 
    page_icon="🚛", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CEREBRO GEOGRÁFICO (DATOS FIJOS) ---

# A. CLIENTES VIP (No buscan en internet, coordenadas fijas)
CLIENTES_VIP = {
    "PREFABRICADOS ZUERA, S.L.": "8FBRV6Q8+PG",
    "Coferdroza": "8FBRV6PP+WR",
    "7 Alimentación 7 S.A.": "8FBRW624+3X",
}

# B. MAPA MENTAL DE ARAGÓN (Referencias para códigos cortos)
# Incluye versiones CON y SIN tilde para evitar errores humanos.
REFERENCIAS_ZONA = {
    # ZONA NORTE / ZUERA
    "ZUERA": (41.8686, -0.7905),
    "ESTACION PORTAZGO": (41.7087, -0.8406),
    "ESTACIÓN PORTAZGO": (41.7087, -0.8406),
    "SAN MATEO": (41.8331, -0.7661),
    "VILLANUEVA": (41.7675, -0.8291),
    "ONTINAR": (41.9333, -0.7833),

    # ZARAGOZA Y ALREDEDORES
    "ZARAGOZA": (41.6488, -0.8891),
    "UTEBO": (41.7145, -0.9966),
    "CUARTE": (41.5947, -0.9333),
    "CADRETE": (41.5719, -0.9427),
    "MARIA DE HUERVA": (41.5422, -0.9625), "MARÍA DE HUERVA": (41.5422, -0.9625),
    "LA PUEBLA": (41.6315, -0.7495),
    "ALAGON": (41.7701, -1.1189), "ALAGÓN": (41.7701, -1.1189),
    "CASETAS": (41.7167, -1.0167),
    "GARRAPINILLOS": (41.6833, -1.0333),
    
    # POLÍGONOS INDUSTRIALES
    "PLAZA": (41.638, -0.962), 
    "MALPICA": (41.656, -0.783),
    "CENTROVIA": (41.624, -1.006), "CENTROVÍA": (41.624, -1.006),
    "PTR": (41.554, -0.885),
    "PRADILLO": (41.785, -1.135),
    "EL PILAR": (41.663, -0.835), # Polígono El Pilar
    
    # RESTO ARAGÓN (CABECERAS)
    "HUESCA": (42.1361, -0.4087),
    "TERUEL": (40.3456, -1.1065),
    "MONZON": (41.9125, 0.1936), "MONZÓN": (41.9125, 0.1936),
    "BARBASTRO": (42.0356, 0.1234),
    "FRAGA": (41.5224, 0.3503),
    "JACA": (42.5703, -0.5486),
    "BINEFAR": (41.8504, 0.2946), "BINÉFAR": (41.8504, 0.2946),
    "SABIÑANIGO": (42.5186, -0.3644), "SABIÑÁNIGO": (42.5186, -0.3644),
    "ALCAÑIZ": (41.0506, -0.1332),
    "CALATAYUD": (41.3524, -1.6416),
    "EJEA": (42.1264, -1.1378),
    "TARAZONA": (41.9048, -1.7259),
    "CASPE": (41.2333, -0.0333),
    "LA ALMUNIA": (41.4687, -1.3746),
    "TAUSTE": (41.9167, -1.2500),
    "EPILA": (41.6006, -1.2801), "ÉPILA": (41.6006, -1.2801)
}

# --- 3. FUNCIONES DEL MOTOR ---

@st.cache_resource
def get_geolocator():
    return Nominatim(user_agent="logistica_aragon_master_v1")

def intentar_decodificar_plus(codigo_bruto, geolocator):
    try:
        codigo_bruto = str(codigo_bruto).strip()
        
        # CASO A: GLOBAL (El mejor)
        if '+' in codigo_bruto and len(codigo_bruto.split('+')[0]) >= 4 and ' ' not in codigo_bruto:
            area = olc.decode(codigo_bruto)
            return area.latitudeCenter, area.longitudeCenter, "GLOBAL 🌐"

        # CASO B: LOCAL (Con Mapa Mental)
        if ' ' in codigo_bruto:
            partes = codigo_bruto.split(' ', 1)
            codigo_corto = partes[0]
            ciudad_ref_raw = partes[1]
            ciudad_ref = ciudad_ref_raw.upper().strip()

            lat_ref, lon_ref, origen_ref = None, None, ""

            # 1. Búsqueda en MEMORIA
            found = False
            for zona, coords in REFERENCIAS_ZONA.items():
                if zona in ciudad_ref: 
                    lat_ref, lon_ref = coords
                    origen_ref = f"AUTO ({zona})"
                    found = True
                    break
            
            # 2. Búsqueda en INTERNET
            if not found:
                loc_ciudad = geolocator.geocode(f"{ciudad_ref_raw}, Aragón, España")
                if loc_ciudad:
                    lat_ref = loc_ciudad.latitude
                    lon_ref = loc_ciudad.longitude
                    origen_ref = "WEB ☁️"

            if lat_ref and lon_ref:
                recuperado = olc.recoverNearest(codigo_corto, lat_ref, lon_ref)
                area = olc.decode(recuperado)
                return area.latitudeCenter, area.longitudeCenter, origen_ref

        return None, None, "ERROR FORMATO"
    except: return None, None, "ERROR"

def obtener_punto_seguro(fila, geolocator):
    nombre = str(fila.get('Cliente', '')).strip()

    # NIVEL VIP
    for vip, codigo in CLIENTES_VIP.items():
        if vip.lower() in nombre.lower():
            lat, lon, met = intentar_decodificar_plus(codigo, geolocator)
            if lat: return lat, lon, "VIP ⭐"

    # NIVEL MANUAL
    l_man = fila.get('Latitud_Manual')
    if pd.notnull(l_man) and str(l_man).strip() != "":
        return float(fila['Latitud_Manual']), float(fila['Longitud_Manual']), "MANUAL"
    
    # NIVEL PLUS CODE
    pcode = fila.get('PlusCode')
    if pd.notnull(pcode) and str(pcode).strip() != "":
        lat, lon, met = intentar_decodificar_plus(pcode, geolocator)
        if lat: return lat, lon, met

    # NIVEL DIRECCIÓN
    d_txt = fila.get('Direccion')
    if pd.notnull(d_txt) and str(d_txt).strip() != "":
        try:
            loc = geolocator.geocode(f"{d_txt}, España")
            if loc: return loc.latitude, loc.longitude, "DIR 🏠"
        except: pass
    
    return None, None, "NO ENCONTRADO ❌"

def optimizar_ruta(puntos, nombres, usar_trafico=True):
    # Obtener matriz
    coords = ";".join([f"{lon},{lat}" for lat, lon in puntos])
    matriz = None
    if usar_trafico:
        try:
            url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=duration"
            r = requests.get(url, timeout=3)
            if r.json()['code'] == 'Ok': matriz = r.json()['durations']
        except: pass
    
    # Algoritmo Vecino Más Cercano
    ruta_indices = [0]
    visitados = {0}
    
    while len(ruta_indices) < len(puntos):
        ultimo = ruta_indices[-1]
        mejor_val = 1e9
        mejor_idx = -1
        
        for i in range(len(puntos)):
            if i not in visitados:
                if matriz: val = matriz[ultimo][i]
                else: val = geodesic(puntos[ultimo], puntos[i]).kilometers
                
                if val < mejor_val:
                    mejor_val = val
                    mejor_idx = i
        
        if mejor_idx != -1:
            ruta_indices.append(mejor_idx)
            visitados.add(mejor_idx)
        else: break
            
    return [puntos[i] for i in ruta_indices], [nombres[i] for i in ruta_indices], (matriz is not None)

def obtener_datos_ruta(puntos):
    coords = ";".join([f"{lon},{lat}" for lat, lon in puntos])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    try:
        r = requests.get(url)
        d = r.json()
        ruta = [[p[1], p[0]] for p in d['routes'][0]['geometry']['coordinates']]
        dist = d['routes'][0]['distance'] / 1000
        dur = d['routes'][0]['duration'] / 60
        return ruta, dist, dur
    except: return None, 0, 0

# --- 4. INTERFAZ GRÁFICA (UI) ---

# --- SIDEBAR (BARRA LATERAL) ---
with st.sidebar:
    st.header("⚙️ Panel de Control")
    st.markdown("---")
    
    st.subheader("🔗 Compartir Herramienta")
    st.info("Copia este enlace para enviarlo a los compañeros:")
    # TRUCO: Como no sabemos la URL exacta de Streamlit Cloud hasta desplegar,
    # le pedimos al usuario que la copie del navegador la primera vez o ponemos un texto genérico.
    st.code("https://logistica-pro-aragon.streamlit.app", language="text")
    st.caption("☝️ *Si tu URL es distinta, cópiala de la barra del navegador.*")
    
    st.markdown("---")
    st.subheader("🚀 Configuración")
    usar_trafico = st.toggle("Usar Tráfico Real (OSRM)", value=True)
    st.markdown("---")
    st.markdown("**Versión:** 3.0 Final")
    st.markdown("**Zona:** Aragón Completo")

# --- PANEL PRINCIPAL ---
st.title("🚛 LOGÍSTICA ARAGÓN | SISTEMA INTELIGENTE")

col1, col2 = st.columns([1, 1.5], gap="large")

with col1:
    st.markdown("### 1. 📂 Cargar Pedidos")
    archivo = st.file_uploader("Arrastra tu Excel aquí", type=["xlsx"])
    
    if archivo:
        df = pd.read_excel(archivo)
        st.write(f"Detectados **{len(df)} clientes**.")
        with st.expander("Ver datos cargados"):
            st.dataframe(df)
            
        if st.button("⚡ CALCULAR RUTA ÓPTIMA", type="primary", use_container_width=True):
            status = st.status("🏗️ Iniciando motor logístico...", expanded=True)
            progreso = st.progress(0)
            
            geolocator = get_geolocator()
            puntos, nombres, errores = [], [], []
            datos_export = [] # Para el Excel final
            
            # FASE 1: GEOCODIFICACIÓN
            for i, fila in df.iterrows():
                cli = str(fila['Cliente'])
                status.write(f"📍 Localizando: **{cli}**...")
                lat, lon, met = obtener_punto_seguro(fila, geolocator)
                
                if lat:
                    puntos.append((lat, lon))
                    nombres.append(cli)
                else:
                    errores.append(cli)
                
                # Sleep solo si usamos internet
                if "WEB" in str(met) or "DIR" in str(met): time.sleep(0.6)
                progreso.progress((i + 1) / len(df) / 2) # 50% del progreso
            
            # FASE 2: OPTIMIZACIÓN
            if len(puntos) > 1:
                status.write("🧠 Optimizando secuencia de paradas...")
                pts_fin, nom_fin, modo = optimizar_ruta(puntos, nombres, usar_trafico)
                
                status.write("🛣️ Dibujando carreteras...")
                trazo, km, mins = obtener_datos_ruta(pts_fin)
                progreso.progress(100)
                
                # Generar link
                base_google = "https://www.google.com/maps/dir/"
                url_g = base_google + "/".join([f"{lat},{lon}" for lat, lon in pts_fin]) + "/"
                
                # Guardar sesión
                st.session_state['res'] = {
                    'p': pts_fin, 'n': nom_fin, 't': trazo, 
                    'k': km, 'm': mins, 'l': url_g, 'e': errores, 'modo': modo
                }
                status.update(label="✅ ¡Ruta Completada!", state="complete", expanded=False)
                st.toast('Ruta calculada con éxito!', icon='🎉')
            else:
                status.update(label="❌ Error: Faltan puntos válidos", state="error")

with col2:
    st.markdown("### 2. 🗺️ Mapa Táctico")
    
    if 'res' in st.session_state:
        r = st.session_state['res']
        
        # TARJETAS DE MÉTRICAS
        k1, k2, k3 = st.columns(3)
        k1.metric("Distancia Total", f"{r['k']:.1f} km", border=True)
        k2.metric("Tiempo Estimado", f"{r['m']:.0f} min", border=True)
        k3.metric("Algoritmo", "Tráfico Real" if r['modo'] else "Línea Recta", border=True)
        
        # MAPA
        m = folium.Map(location=r['p'][0], zoom_start=11)
        if r['t']: 
            folium.PolyLine(r['t'], weight=5, color="#2563EB", opacity=0.8).add_to(m)
        
        for i, (lat, lon) in enumerate(r['p']):
            icon_color = "green" if i == 0 else "red" if i == len(r['p'])-1 else "blue"
            icon_type = "play" if i == 0 else "stop" if i == len(r['p'])-1 else "truck"
            
            folium.Marker(
                [lat, lon],
                popup=f"<b>{i+1}. {r['n'][i]}</b>",
                icon=folium.Icon(color=icon_color, icon=icon_type, prefix="fa")
            ).add_to(m)
        
        st_folium(m, use_container_width=True, height=500)
        
        # ZONA DE ACCIÓN
        st.markdown("### 3. 📤 Exportar y Enviar")
        
        c_wa, c_ex = st.columns(2)
        
        # BOTÓN WHATSAPP
        with c_wa:
            msg = f"🚚 *RUTA DE HOY* 🚚\n\n📏 {r['k']:.1f} km\n⏱️ {r['m']:.0f} min\n\n🗺️ *Enlace:* {r['l']}"
            link_wa = f"https://wa.me/?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
            st.link_button("📲 ENVIAR WHATSAPP", link_wa, type="primary", use_container_width=True)

        # BOTÓN EXCEL (NUEVO)
        with c_ex:
            # Crear Excel en memoria
            df_export = pd.DataFrame({
                "Orden": range(1, len(r['n']) + 1),
                "Cliente": r['n'],
                "Coordenadas": [f"{lat},{lon}" for lat, lon in r['p']]
            })
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
                df_export.to_excel(writer, index=False, sheet_name='Ruta Optimizada')
            
            st.download_button(
                label="📥 DESCARGAR EXCEL",
                data=buffer.getvalue(),
                file_name="ruta_optimizada.xlsx",
                mime="application/vnd.ms-excel",
                use_container_width=True
            )

        # ERRORES
        if r['e']:
            st.error(f"⚠️ No se encontraron: {', '.join(r['e'])}")
            
    else:
        st.info("👈 Sube tu archivo y calcula para ver el mapa.")
        st.image("https://cdn-icons-png.flaticon.com/512/854/854878.png", width=100, caption="Esperando datos...")