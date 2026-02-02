import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import requests
import time
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from openlocationcode import openlocationcode as olc
import io
import unicodedata

# --- 1. CONFIGURACIÓN ---
st.set_page_config(
    page_title="LOGÍSTICA ARAGÓN | FINANZAS", 
    page_icon="💶", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- 2. CEREBRO GEOGRÁFICO ---
CLIENTES_VIP = {
    "PREFABRICADOS ZUERA, S.L.": "8FBRV6Q8+PG",
    "Coferdroza": "8FBRV6PP+WR",
    "7 Alimentación 7 S.A.": "8FBRW624+3X",
}

REFERENCIAS_ZONA = {
    "ZUERA": (41.8686, -0.7905),
    "ESTACION PORTAZGO": (41.7087, -0.8406), "ESTACIÓN PORTAZGO": (41.7087, -0.8406),
    "SAN MATEO": (41.8331, -0.7661), "VILLANUEVA": (41.7675, -0.8291), "ONTINAR": (41.9333, -0.7833),
    "ZARAGOZA": (41.6488, -0.8891), "UTEBO": (41.7145, -0.9966), "CUARTE": (41.5947, -0.9333),
    "CADRETE": (41.5719, -0.9427), "MARIA DE HUERVA": (41.5422, -0.9625), "MARÍA DE HUERVA": (41.5422, -0.9625),
    "LA PUEBLA": (41.6315, -0.7495), "ALAGON": (41.7701, -1.1189), "ALAGÓN": (41.7701, -1.1189),
    "CASETAS": (41.7167, -1.0167), "GARRAPINILLOS": (41.6833, -1.0333),
    "PLAZA": (41.638, -0.962), "MALPICA": (41.656, -0.783), "CENTROVIA": (41.624, -1.006), "CENTROVÍA": (41.624, -1.006),
    "PTR": (41.554, -0.885), "PRADILLO": (41.785, -1.135), "EL PILAR": (41.663, -0.835),
    "HUESCA": (42.1361, -0.4087), "TERUEL": (40.3456, -1.1065),
    "MONZON": (41.9125, 0.1936), "MONZÓN": (41.9125, 0.1936),
    "BARBASTRO": (42.0356, 0.1234), "FRAGA": (41.5224, 0.3503),
    "JACA": (42.5703, -0.5486), "BINEFAR": (41.8504, 0.2946), "BINÉFAR": (41.8504, 0.2946),
    "SABIÑANIGO": (42.5186, -0.3644), "SABIÑÁNIGO": (42.5186, -0.3644),
    "ALCAÑIZ": (41.0506, -0.1332), "CALATAYUD": (41.3524, -1.6416), "EJEA": (42.1264, -1.1378),
    "TARAZONA": (41.9048, -1.7259), "CASPE": (41.2333, -0.0333), "LA ALMUNIA": (41.4687, -1.3746),
    "TAUSTE": (41.9167, -1.2500), "EPILA": (41.6006, -1.2801), "ÉPILA": (41.6006, -1.2801)
}

# --- 3. FUNCIONES DEL MOTOR ---
@st.cache_resource
def get_geolocator():
    return Nominatim(user_agent="logistica_aragon_finance_v1")

def intentar_decodificar_plus(codigo_bruto, geolocator):
    try:
        codigo_bruto = str(codigo_bruto).strip()
        if '+' in codigo_bruto and len(codigo_bruto.split('+')[0]) >= 4 and ' ' not in codigo_bruto:
            area = olc.decode(codigo_bruto)
            return area.latitudeCenter, area.longitudeCenter, "GLOBAL 🌐"
        if ' ' in codigo_bruto:
            partes = codigo_bruto.split(' ', 1)
            codigo_corto = partes[0]
            ciudad_ref_raw = partes[1]
            ciudad_ref = ciudad_ref_raw.upper().strip()
            lat_ref, lon_ref, origen_ref = None, None, ""
            found = False
            for zona, coords in REFERENCIAS_ZONA.items():
                if zona in ciudad_ref: 
                    lat_ref, lon_ref = coords; origen_ref = f"AUTO ({zona})"; found = True; break
            if not found:
                loc_ciudad = geolocator.geocode(f"{ciudad_ref_raw}, Aragón, España")
                if loc_ciudad: lat_ref, lon_ref, origen_ref = loc_ciudad.latitude, loc_ciudad.longitude, "WEB ☁️"
            if lat_ref and lon_ref:
                recuperado = olc.recoverNearest(codigo_corto, lat_ref, lon_ref)
                area = olc.decode(recuperado)
                return area.latitudeCenter, area.longitudeCenter, origen_ref
        return None, None, "ERROR FORMATO"
    except: return None, None, "ERROR"

def obtener_punto_seguro(fila, geolocator):
    nombre = str(fila.get('Cliente', '')).strip()
    for vip, codigo in CLIENTES_VIP.items():
        if vip.lower() in nombre.lower():
            lat, lon, met = intentar_decodificar_plus(codigo, geolocator)
            if lat: return lat, lon, "VIP ⭐"
    l_man = fila.get('Latitud_Manual')
    if pd.notnull(l_man) and str(l_man).strip() != "":
        return float(fila['Latitud_Manual']), float(fila['Longitud_Manual']), "MANUAL"
    pcode = fila.get('PlusCode')
    if pd.notnull(pcode) and str(pcode).strip() != "":
        lat, lon, met = intentar_decodificar_plus(pcode, geolocator)
        if lat: return lat, lon, met
    d_txt = fila.get('Direccion')
    if pd.notnull(d_txt) and str(d_txt).strip() != "":
        try:
            loc = geolocator.geocode(f"{d_txt}, España")
            if loc: return loc.latitude, loc.longitude, "DIR 🏠"
        except: pass
    return None, None, "NO ENCONTRADO ❌"

def optimizar_ruta(puntos, nombres):
    coords = ";".join([f"{lon},{lat}" for lat, lon in puntos])
    matriz = None
    try:
        url = f"http://router.project-osrm.org/table/v1/driving/{coords}?annotations=distance"
        r = requests.get(url, timeout=3)
        if r.json()['code'] == 'Ok': matriz = r.json()['distances']
    except: pass
    ruta_indices = [0]; visitados = {0}
    while len(ruta_indices) < len(puntos):
        ultimo = ruta_indices[-1]; mejor_val = 1e9; mejor_idx = -1
        for i in range(len(puntos)):
            if i not in visitados:
                val = matriz[ultimo][i] if matriz else geodesic(puntos[ultimo], puntos[i]).kilometers
                if val < mejor_val: mejor_val = val; mejor_idx = i
        if mejor_idx != -1: ruta_indices.append(mejor_idx); visitados.add(mejor_idx)
        else: break
    return [puntos[i] for i in ruta_indices], [nombres[i] for i in ruta_indices]

def obtener_datos_ruta(puntos):
    coords = ";".join([f"{lon},{lat}" for lat, lon in puntos])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}?overview=full&geometries=geojson"
    try:
        r = requests.get(url)
        d = r.json()
        ruta = [[p[1], p[0]] for p in d['routes'][0]['geometry']['coordinates']]
        dist = d['routes'][0]['distance'] / 1000
        # OSRM devuelve duración en segundos
        dur_min = d['routes'][0]['duration'] / 60 
        return ruta, dist, dur_min
    except: return None, 0, 0

# --- 4. INTERFAZ GRÁFICA (UI) ---

with st.sidebar:
    st.header("⚙️ Configuración")
    
    st.markdown("### 💶 Estructura de Costes")
    st.info("Introduce tus costes reales para calcular rentabilidad.")
    
    # INPUTS FINANCIEROS
    coste_km = st.number_input("Coste Vehículo (€/km)", value=0.35, step=0.01, format="%.2f", help="Incluye gasolina, mantenimiento y seguro.")
    coste_hora = st.number_input("Coste Chofer (€/hora)", value=15.00, step=0.50, format="%.2f", help="Salario bruto + SS prorrateado.")
    
    st.markdown("---")
    st.subheader("🔗 Compartir")
    st.code("https://logistica-pro-aragon.streamlit.app", language="text")

st.title("🚛 LOGÍSTICA ARAGÓN | FINANZAS")

col1, col2 = st.columns([1, 1.5], gap="large")

with col1:
    st.markdown("### 1. 📂 Cargar Pedidos")
    archivo = st.file_uploader("Sube Excel", type=["xlsx"])
    
    if archivo:
        df = pd.read_excel(archivo)
        if st.button("⚡ CALCULAR COSTES Y RUTA", type="primary", use_container_width=True):
            status = st.status("🏗️ Auditando ubicaciones...", expanded=True)
            progreso = st.progress(0)
            geolocator = get_geolocator()
            puntos, nombres, errores = [], [], []
            
            for i, fila in df.iterrows():
                cli = str(fila['Cliente'])
                status.write(f"📍 {cli}...")
                lat, lon, met = obtener_punto_seguro(fila, geolocator)
                if lat: puntos.append((lat, lon)); nombres.append(cli)
                else: errores.append(cli)
                if "WEB" in str(met) or "DIR" in str(met): time.sleep(0.6)
                progreso.progress((i + 1) / len(df) / 2)
            
            if len(puntos) > 1:
                status.write("🧠 Maximizando eficiencia...")
                pts_fin, nom_fin = optimizar_ruta(puntos, nombres)
                
                status.write("🛣️ Calculando impacto económico...")
                trazo, km, minutos_viaje = obtener_datos_ruta(pts_fin)
                progreso.progress(100)
                
                # CÁLCULOS FINANCIEROS
                total_coste_km = km * coste_km
                # Añadimos 15 min por parada de carga/descarga
                minutos_paradas = len(pts_fin) * 15 
                tiempo_total_horas = (minutos_viaje + minutos_paradas) / 60
                total_coste_chofer = tiempo_total_horas * coste_hora
                coste_total = total_coste_km + total_coste_chofer
                
                base_google = "https://www.google.com/maps/dir/"
                url_g = base_google + "/".join([f"{lat},{lon}" for lat, lon in pts_fin]) + "/"
                
                st.session_state['res'] = {
                    'p': pts_fin, 'n': nom_fin, 't': trazo, 'k': km, 'l': url_g, 'e': errores,
                    'finanzas': {
                        'coste_total': coste_total,
                        'coste_km': total_coste_km,
                        'coste_chofer': total_coste_chofer,
                        'tiempo_h': tiempo_total_horas
                    }
                }
                status.update(label="✅ ¡Auditoría Completada!", state="complete", expanded=False)
            else: status.update(label="❌ Datos insuficientes", state="error")

with col2:
    st.markdown("### 2. 📊 Auditoría Económica")
    
    if 'res' in st.session_state:
        r = st.session_state['res']
        fin = r['finanzas']
        
        # TARJETAS DE IMPACTO
        c1, c2, c3 = st.columns(3)
        c1.metric("COSTE TOTAL", f"{fin['coste_total']:.2f} €", delta="Estimado", delta_color="inverse")
        c2.metric("Coste Gasolina/Vehículo", f"{fin['coste_km']:.2f} €")
        c3.metric("Coste Personal", f"{fin['coste_chofer']:.2f} €")
        
        st.caption(f"*Cálculo basado en: {r['k']:.1f} km de ruta + {fin['tiempo_h']:.1f} horas de trabajo (incluyendo 15min/parada).*")
        
        m = folium.Map(location=r['p'][0], zoom_start=11)
        if r['t']: folium.PolyLine(r['t'], weight=5, color="#2563EB", opacity=0.8).add_to(m)
        for i, (lat, lon) in enumerate(r['p']):
            folium.Marker([lat, lon], popup=f"{i+1}. {r['n'][i]}", icon=folium.Icon(color="green" if i==0 else "blue", icon="truck", prefix="fa")).add_to(m)
        st_folium(m, use_container_width=True, height=450)
        
        st.markdown("### 3. 📤 Operaciones")
        c_wa, c_ex = st.columns(2)
        with c_wa:
            msg = f"🚛 *ORDEN DE CARGA* 🚚\n\n💰 Coste Previsto: {fin['coste_total']:.0f}€\n📍 {len(r['p'])} Clientes\n📏 {r['k']:.1f} km\n\n🗺️ *Mapa:* {r['l']}"
            link_wa = f"https://wa.me/?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
            st.link_button("📲 ENVIAR ORDEN", link_wa, type="primary", use_container_width=True)
        with c_ex:
            df_export = pd.DataFrame({"Orden": range(1, len(r['n']) + 1), "Cliente": r['n'], "Coordenadas": [f"{lat},{lon}" for lat, lon in r['p']]})
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer: df_export.to_excel(writer, index=False)
            st.download_button("📥 DESCARGAR INFORME", buffer.getvalue(), "informe_ruta.xlsx", "application/vnd.ms-excel", use_container_width=True)
            
        if r['e']: st.error(f"⚠️ Sin localizar: {', '.join(r['e'])}")
    else:
        st.info("Configura los costes en la izquierda y sube el Excel.")