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
st.set_page_config(page_title="LOGÍSTICA ARAGÓN PRO", page_icon="🦁", layout="wide")

# --- 1. MEMORIA VIP (Clientes Fijos) ---
CLIENTES_VIP = {
    "PREFABRICADOS ZUERA, S.L.": "8FBRV6Q8+PG",
    "Coferdroza": "8FBRV6PP+WR",
    "7 Alimentación 7 S.A.": "8FBRW624+3X",
    "STELLANTIS (OPEL)": "8FBRQMXP+22", # Ejemplo
    "MERCAZARAGOZA": "8FBRMJWC+55",   # Ejemplo
}

# --- 2. MAPA MENTAL DE ARAGÓN (REFERENCIAS FIJAS) 🧠 ---
# Coordenadas centrales para decodificar códigos cortos al instante.
REFERENCIAS_ZONA = {
    # --- ZARAGOZA Y ALREDEDORES ---
    "ZARAGOZA": (41.6488, -0.8891),
    "UTEBO": (41.7145, -0.9966),
    "CUARTE": (41.5947, -0.9333),
    "CUARTE DE HUERVA": (41.5947, -0.9333),
    "CADRETE": (41.5719, -0.9427),
    "MARIA DE HUERVA": (41.5422, -0.9625),
    "LA PUEBLA DE ALFINDEN": (41.6315, -0.7495),
    "LA PUEBLA": (41.6315, -0.7495),
    "ZUERA": (41.8686, -0.7905),
    "SAN MATEO": (41.8331, -0.7661),
    "VILLANUEVA": (41.7675, -0.8291),
    "EL BURGO": (41.5721, -0.7554),
    "ALAGON": (41.7701, -1.1189),
    "CASETAS": (41.7167, -1.0167),
    "GARRAPINILLOS": (41.6833, -1.0333),
    "ESTACION PORTAZGO": (41.7087, -0.8406),
    
    # --- POLÍGONOS CLAVE ---
    "PLAZA": (41.638, -0.962), # Plataforma Logística
    "MALPICA": (41.656, -0.783),
    "CENTROVIA": (41.624, -1.006),
    "PTR": (41.554, -0.885),
    "PRADILLO": (41.785, -1.135), # Pedrola
    
    # --- PROVINCIA ZARAGOZA ---
    "CALATAYUD": (41.3524, -1.6416),
    "EJEA": (42.1264, -1.1378),
    "TARAZONA": (41.9048, -1.7259),
    "CASPE": (41.2333, -0.0333),
    "LA ALMUNIA": (41.4687, -1.3746),
    "TAUSTE": (41.9167, -1.2500),
    "EPILA": (41.6006, -1.2801),
    "PEDROLA": (41.7915, -1.2144),
    "BORJA": (41.8344, -1.5317),
    "CARIÑENA": (41.3383, -1.2242),
    
    # --- PROVINCIA HUESCA ---
    "HUESCA": (42.1361, -0.4087),
    "MONZON": (41.9125, 0.1936),
    "BARBASTRO": (42.0356, 0.1234),
    "FRAGA": (41.5224, 0.3503),
    "JACA": (42.5703, -0.5486),
    "BINEFAR": (41.8504, 0.2946),
    "SABIÑANIGO": (42.5186, -0.3644),
    "SARIÑENA": (41.7933, -0.1578),
    "GRAUS": (42.1889, 0.3389),
    "WALQA": (42.1067, -0.4431),
    
    # --- PROVINCIA TERUEL ---
    "TERUEL": (40.3456, -1.1065),
    "ALCAÑIZ": (41.0506, -0.1332),
    "ANDORRA": (40.9757, -0.4472),
    "CALAMOCHA": (40.9167, -1.3000),
    "UTRILLAS": (40.8167, -0.8500),
    "VALDERROBRES": (40.8750, 0.1500),
    "CELLA": (40.4500, -1.2833)
}

# --- FUNCIONES DEL MOTOR ---
@st.cache_resource
def get_geolocator():
    return Nominatim(user_agent="sistema_logistico_aragon_full_v4")

def intentar_decodificar_plus(codigo_bruto, geolocator):
    try:
        codigo_bruto = str(codigo_bruto).strip()
        
        # CASO A: GLOBAL (Ej: 8FBR...)
        if '+' in codigo_bruto and len(codigo_bruto.split('+')[0]) >= 4 and ' ' not in codigo_bruto:
            area = olc.decode(codigo_bruto)
            return area.latitudeCenter, area.longitudeCenter, "GLOBAL 🌐"

        # CASO B: LOCAL (Ej: W624+3X Monzón)
        if ' ' in codigo_bruto:
            partes = codigo_bruto.split(' ', 1)
            codigo_corto = partes[0]
            ciudad_ref_raw = partes[1]
            ciudad_ref = ciudad_ref_raw.upper().strip()

            lat_ref = None
            lon_ref = None
            origen_ref = ""

            # 1. Búsqueda en MAPA MENTAL (Instantánea)
            found = False
            for zona, coords in REFERENCIAS_ZONA.items():
                if zona in ciudad_ref: # Si "MONZON" está en "Monzón"
                    lat_ref, lon_ref = coords
                    origen_ref = f"AUTO-ARAGÓN ({zona})"
                    found = True
                    break
            
            # 2. Búsqueda en INTERNET (Respaldo)
            if not found:
                loc_ciudad = geolocator.geocode(f"{ciudad_ref_raw}, Aragón, España")
                if loc_ciudad:
                    lat_ref = loc_ciudad.latitude
                    lon_ref = loc_ciudad.longitude
                    origen_ref = "INTERNET ☁️"

            # 3. Cálculo matemático
            if lat_ref and lon_ref:
                recuperado = olc.recoverNearest(codigo_corto, lat_ref, lon_ref)
                area = olc.decode(recuperado)
                return area.latitudeCenter, area.longitudeCenter, origen_ref

        return None, None, "ERROR FORMATO"
    except Exception as e: 
        return None, None, "ERROR"

def obtener_punto_seguro(fila, geolocator):
    nombre_cliente = str(fila.get('Cliente', '')).strip()

    # NIVEL 0: MEMORIA VIP
    for vip, codigo in CLIENTES_VIP.items():
        if vip.lower() in nombre_cliente.lower():
            lat, lon, met = intentar_decodificar_plus(codigo, geolocator)
            if lat: return lat, lon, "MEMORIA VIP ⭐"

    # NIVEL 1: Manual
    lat_man = fila.get('Latitud_Manual')
    lon_man = fila.get('Longitud_Manual')
    if pd.notnull(lat_man) and pd.notnull(lon_man) and str(lat_man).strip() != "":
        return float(lat_man), float(lon_man), "MANUAL"
    
    # NIVEL 2: Plus Code (Aquí usamos el mapa de Aragón)
    pcode = fila.get('PlusCode')
    if pd.notnull(pcode) and str(pcode).strip() != "":
        lat, lon, met = intentar_decodificar_plus(pcode, geolocator)
        if lat: return lat, lon, met

    # NIVEL 3: Dirección
    dir_txt = fila.get('Direccion')
    if pd.notnull(dir_txt) and str(dir_txt).strip() != "":
        try:
            busqueda = dir_txt if "España" in dir_txt else f"{dir_txt}, España"
            loc = geolocator.geocode(busqueda)
            if loc: return loc.latitude, loc.longitude, "DIRECCION 🏠"
        except: pass
    
    return None, None, "NO ENCONTRADO ❌"

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
                if val < mejor_val: mejor_val = val; mejor_idx = i
        if mejor_idx != -1: ruta_indices.append(mejor_idx); visitados.add(mejor_idx)
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
        r = requests.get(url); d = r.json()
        ruta = [[p[1], p[0]] for p in d['routes'][0]['geometry']['coordinates']]
        dist = d['routes'][0]['distance']/1000; dur = d['routes'][0]['duration']/60
        return ruta, dist, dur
    except: return None, 0, 0

# --- INTERFAZ ---
st.title("🚚 Sistema de Rutas - Aragón")
st.markdown("""<style>div.stButton > button:first-child {background-color: #D32F2F; color: white; width: 100%;}</style>""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])
with col1:
    st.markdown("### 1. Cargar Excel")
    st.info("💡 Acepta códigos de todo Aragón (ej: 'Monzón', 'Alcañiz', 'PLAZA').")
    archivo = st.file_uploader("Sube ruta_hoy.xlsx", type=["xlsx"])
    if archivo:
        df = pd.read_excel(archivo)
        st.write(f"📂 {len(df)} clientes.")
        if st.button("🚀 CALCULAR RUTA", type="primary"):
            status = st.empty(); bar = st.progress(0)
            geolocator = get_geolocator()
            puntos_ok, nombres_ok, errores = [], [], []
            
            for i, fila in df.iterrows():
                cli = str(fila['Cliente'])
                status.text(f"🔍 {cli}...")
                lat, lon, met = obtener_punto_seguro(fila, geolocator)
                
                if lat: puntos_ok.append((lat, lon)); nombres_ok.append(cli)
                else: errores.append(cli)
                
                # Si usamos AUTO-ARAGON o MEMORIA, no esperamos
                if "INTERNET" in str(met) or "DIRECCION" in str(met): time.sleep(0.5)
                bar.progress((i + 1) / len(df))
            
            if len(puntos_ok) < 2: st.error("Faltan puntos.")
            else:
                pts_final, noms_final, time_mode = optimizar_ruta(puntos_ok, nombres_ok)
                trazo, km, mins = obtener_trazo_osrm(pts_final)
                link = generar_link_google(pts_final)
                st.session_state['res'] = {'p': pts_final, 'n': noms_final, 't': trazo, 'k': km, 'm': mins, 'l': link, 'e': errores, 'tm': time_mode}
                status.success("✅ ¡Hecho!")

with col2:
    if 'res' in st.session_state:
        r = st.session_state['res']
        c1, c2, c3 = st.columns(3)
        c1.metric("Km", f"{r['k']:.1f}"); c2.metric("Min", f"{r['m']:.0f}"); c3.metric("Modo", "IA Tráfico" if r['tm'] else "Recta")
        m = folium.Map(location=r['p'][0], zoom_start=11)
        if r['t']: folium.PolyLine(r['t'], weight=5).add_to(m)
        for i, (lat, lon) in enumerate(r['p']):
            folium.Marker([lat, lon], popup=f"{i+1}. {r['n'][i]}", icon=folium.Icon(color="red" if i==0 else "blue", icon="truck", prefix="fa")).add_to(m)
        st_folium(m, height=500, use_container_width=True)
        if r['e']: st.error(f"❌ Fallos: {', '.join(r['e'])}")
        st.link_button("📲 ENVIAR WHATSAPP", f"https://wa.me/?text=Ruta%20({r['k']:.1f}km):%20{r['l']}", type="primary")