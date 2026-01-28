import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import time
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from openlocationcode import openlocationcode as olc

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="LOGÍSTICA PRO v1", page_icon="🚚", layout="wide")

# --- FUNCIONES DEL MOTOR (TU CÓDIGO V7) ---
@st.cache_resource # Esto hace que no se reconecte mil veces
def get_geolocator():
    return Nominatim(user_agent="sistema_logistico_web_v1")

def intentar_decodificar_plus(codigo_bruto, geolocator):
    try:
        codigo_bruto = str(codigo_bruto).strip()
        if '+' in codigo_bruto and len(codigo_bruto.split('+')[0]) >= 4 and ' ' not in codigo_bruto:
            area = olc.decode(codigo_bruto)
            return area.latitudeCenter, area.longitudeCenter, "PLUS GLOBAL"
        if ' ' in codigo_bruto:
            partes = codigo_bruto.split(' ', 1)
            codigo_corto = partes[0]
            ciudad_ref = partes[1]
            loc_ciudad = geolocator.geocode(f"{ciudad_ref}, España")
            if loc_ciudad:
                recuperado = olc.recoverNearest(codigo_corto, loc_ciudad.latitude, loc_ciudad.longitude)
                area = olc.decode(recuperado)
                return area.latitudeCenter, area.longitudeCenter, f"PLUS LOCAL"
        return None, None, "ERROR"
    except: return None, None, "ERROR"

def obtener_punto_seguro(fila, geolocator):
    # 1. Manual
    lat_man = fila.get('Latitud_Manual')
    lon_man = fila.get('Longitud_Manual')
    if pd.notnull(lat_man) and pd.notnull(lon_man) and str(lat_man).strip() != "":
        return float(lat_man), float(lon_man), "MANUAL"
    
    # 2. Plus Code
    pcode = fila.get('PlusCode')
    if pd.notnull(pcode) and str(pcode).strip() != "":
        lat, lon, met = intentar_decodificar_plus(pcode, geolocator)
        if lat: return lat, lon, met

    # 3. Dirección
    dir_txt = fila.get('Direccion')
    if pd.notnull(dir_txt) and str(dir_txt).strip() != "":
        try:
            busqueda = dir_txt if "España" in dir_txt else f"{dir_txt}, España"
            loc = geolocator.geocode(busqueda)
            if loc: return loc.latitude, loc.longitude, "DIRECCION"
        except: pass
    
    return None, None, "NO ENCONTRADO"

def obtener_matriz_tiempos(puntos):
    coords = ";".join([f"{lon},{lat}" for lat, lon in puntos])
    url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=duration"
    try:
        r = requests.get(url, timeout=4)
        data = r.json()
        if data['code'] == 'Ok': return data['durations']
    except: pass
    return None

def optimizar_ruta(puntos, nombres):
    matriz = obtener_matriz_tiempos(puntos)
    usando_tiempo = True if matriz else False
    
    ruta_indices = [0]
    visitados = {0}
    
    while len(ruta_indices) < len(puntos):
        ultimo = ruta_indices[-1]
        mejor_val = 9999999999
        mejor_idx = -1
        
        for i in range(len(puntos)):
            if i not in visitados:
                val = matriz[ultimo][i] if usando_tiempo else geodesic(puntos[ultimo], puntos[i]).kilometers
                if val < mejor_val:
                    mejor_val = val
                    mejor_idx = i
        
        if mejor_idx != -1:
            ruta_indices.append(mejor_idx)
            visitados.add(mejor_idx)
        else: break
            
    return [puntos[i] for i in ruta_indices], [nombres[i] for i in ruta_indices], usando_tiempo

def generar_link_google(puntos):
    base = "https://www.google.com/maps/dir/"
    url = ""
    for lat, lon in puntos: url += f"{lat},{lon}/"
    return base + url

def obtener_trazo_osrm(puntos):
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

# --- INTERFAZ GRÁFICA (FRONTEND) ---

# --- INTERFAZ GRÁFICA (FRONTEND OPTIMIZADO) ---

st.title("🚚 Sistema de Rutas Inteligente")
st.markdown("""
<style>
    .big-font { font-size:20px !important; }
    div.stButton > button:first-child {
        background-color: #00cc00; color: white; font-size: 20px; border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])

with col1:
    st.markdown("### 1. Panel de Control")
    st.info("💡 Consejo: Usa **Plus Code Global** (ej: 8FBR...) para velocidad INSTANTÁNEA.")
    archivo = st.file_uploader("Sube tu Excel", type=["xlsx"])
    
    if archivo:
        df = pd.read_excel(archivo)
        st.write(f"📂 Cargadas {len(df)} filas.")
        
        # Botón grande
        if st.button("🚀 CALCULAR RUTA AHORA", type="primary"):
            
            # Contenedor para mostrar qué está pasando
            status_text = st.empty()
            progreso = st.progress(0)
            
            geolocator = get_geolocator()
            puntos_ok = []
            nombres_ok = []
            errores = []
            
            total = len(df)
            start_time = time.time()
            
            for i, fila in df.iterrows():
                cli = str(fila['Cliente'])
                
                # Actualizamos el texto para que veas que NO está colgado
                status_text.text(f"🔍 Procesando {i+1}/{total}: {cli}...")
                
                lat, lon, met = obtener_punto_seguro(fila, geolocator)
                
                if lat:
                    puntos_ok.append((lat, lon))
                    nombres_ok.append(cli)
                else:
                    errores.append(cli)
                
                # OPTIMIZACIÓN DE TIEMPO:
                # Solo esperamos si estamos buscando en internet (Dirección o Local)
                # Si es Manual o Global, vuela.
                if "DIRECCION" in met or "LOCAL" in met: 
                    time.sleep(0.3) # Reducido de 0.8 a 0.3 (Más rápido)
                
                progreso.progress((i + 1) / total)
            
            tiempo_total = time.time() - start_time
            status_text.success(f"✅ Procesado en {tiempo_total:.1f} segundos.")
            
            if len(puntos_ok) < 2:
                st.error("❌ No hay suficientes puntos válidos.")
            else:
                with st.spinner('🧠 Optimizando ruta con IA...'):
                    pts_finales, noms_finales, uso_tiempo = optimizar_ruta(puntos_ok, nombres_ok)
                    trazo, km, mins = obtener_trazo_osrm(pts_finales)
                    link = generar_link_google(pts_finales)
                
                st.session_state['resultado'] = {
                    'puntos': pts_finales,
                    'nombres': noms_finales,
                    'trazo': trazo,
                    'km': km,
                    'mins': mins,
                    'link': link,
                    'errores': errores,
                    'uso_tiempo': uso_tiempo
                }

with col2:
    st.markdown("### 2. Visualización Táctica")
    
    if 'resultado' in st.session_state:
        res = st.session_state['resultado']
        
        # Métricas Bonitas
        c1, c2, c3 = st.columns(3)
        c1.metric("🛣️ Distancia", f"{res['km']:.1f} km")
        c2.metric("⏱️ Tiempo", f"{res['mins']:.0f} min")
        c3.metric("🧠 IA", "Tráfico Real" if res['uso_tiempo'] else "Línea Recta")
        
        # Mapa
        m = folium.Map(location=res['puntos'][0], zoom_start=12)
        
        if res['trazo']:
            folium.PolyLine(res['trazo'], color="#2980b9", weight=6, opacity=0.8).add_to(m)
        
        for i, (lat, lon) in enumerate(res['puntos']):
            color = "red" if i == 0 else "blue"
            folium.Marker(
                [lat, lon],
                popup=f"<b>{i+1}. {res['nombres'][i]}</b>",
                icon=folium.Icon(color=color, icon="truck", prefix="fa")
            ).add_to(m)
            
        st_folium(m, use_container_width=True, height=500)
        
        if res['errores']:
            st.error(f"❌ No se encontraron: {', '.join(res['errores'])}")
    
    # --- SECCIÓN DE ENTREGABLES MEJORADA ---
        st.markdown("### 3. Centro de Mando")
        
        # 1. El Enlace Puro (Con botón de copia integrado en la esquina)
        st.markdown("**🔗 Link de la Ruta:**")
        st.code(res['link'], language="text")
        
        # 2. El Botón Mágico de WhatsApp
        # Creamos un mensaje pre-formateado
        mensaje_wa = f"Hola, aquí tienes la ruta de hoy ({res['km']:.1f} km). Dale caña: {res['link']}"
        link_whatsapp = f"https://wa.me/?text={mensaje_wa.replace(' ', '%20')}"
        
        st.link_button("📲 ABRIR WHATSAPP Y ENVIAR", link_whatsapp, type="primary")
        
    else:
        st.info("👈 Sube el Excel y calcula para ver el mapa aquí.")