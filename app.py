import streamlit as st

# MUST be first Streamlit command
st.set_page_config(
    page_title="Apprentis d'Auteuil - Carte",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

import streamlit.components.v1 as components
import folium
import pandas as pd
import json
import os

# ============================================
# CONFIGURATION
# ============================================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

CATEGORY_COLORS = {
    "Formation : 1ier deg": "#1e90ff",
    "Formation : College": "#4169e1",
    "Formation : Lycee pro": "#0000cd",
    "Formation : Lycee pro agricole": "#00008b",
    "Formation : Post-bac": "#191970",
    "Protection de l'enfance : MECs MNA": "#ff6347",
    "Protection de l'enfance : MECs Fratrie": "#dc143c",
    "Protection de l'enfance : MECs AEMO": "#b22222",
    "Protection de l'enfance : MECs Semi autnomie": "#8b0000",
    "Insertion: Dispo insertion": "#32cd32",
    "Inserttion : IAE": "#228b22",
    "Parentialité : Maison des familles": "#9370db",
    "Parentalité : Creches": "#8a2be2",
    "Parentalité : Autres dispositifs parentalité": "#4b0082",
}

MAIN_COLORS = {
    "Formation": "#4169e1",
    "Protection": "#dc143c",
    "Insertion": "#32cd32",
    "Parentalité": "#9370db",
}

def get_main_cat(cat):
    if pd.isna(cat): return "Autre"
    cat = str(cat)
    if "Formation" in cat: return "Formation"
    if "Protection" in cat: return "Protection"
    if "Insertion" in cat: return "Insertion"
    if "Parent" in cat: return "Parentalité"
    return "Autre"

# ============================================
# DATA LOADING (cached, shared across users)
# ============================================

@st.cache_resource
def load_establishments():
    """Load establishment data - cached across all users"""
    path = os.path.join(SCRIPT_DIR, "Draft etablissements_categorized.csv")
    df = pd.read_csv(path, encoding='utf-8')
    df = df.dropna(subset=['lat', 'lng'])
    # Filter to mainland France
    df = df[(df['lat'] >= 41) & (df['lat'] <= 52) & (df['lng'] >= -6) & (df['lng'] <= 10)]
    return df

@st.cache_resource
def load_json_file(filename):
    """Load JSON file - cached across all users"""
    path = os.path.join(SCRIPT_DIR, filename)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

@st.cache_resource
def load_qpv():
    """Load QPV data filtered to mainland France"""
    data = load_json_file("QP2024_France_Hexagonale_Outre_Mer_WGS84.geojson")
    if data:
        # Filter to mainland France (dept codes 01-95, 2A, 2B)
        data['features'] = [
            f for f in data['features']
            if len(str(f.get('properties', {}).get('insee_dep', ''))) <= 2
            or str(f.get('properties', {}).get('insee_dep', '')).startswith('2')
        ]
    return data

@st.cache_resource
def load_epci():
    """Load EPCI data filtered to mainland France"""
    data = load_json_file("epci_2025_complete.geojson")
    if data:
        # Filter out overseas (codes starting with 97x)
        overseas = ['97', '98']
        data['features'] = [
            f for f in data['features']
            if not any(str(f.get('properties', {}).get('codgeo', '')).startswith(p) for p in overseas)
        ]
    return data

@st.cache_resource
def load_isochrones():
    """Load isochrone cache"""
    return load_json_file("isochrone_cache.json") or {}

# ============================================
# BUILD MAP HTML (cached, shared across users)
# ============================================

@st.cache_resource
def build_map_html():
    """
    Build the complete map and return HTML.
    This is cached and shared across ALL users.
    Map interactions (zoom, pan, layer toggle) are pure JavaScript.
    """
    
    # Load all data
    df = load_establishments()
    qpv = load_qpv()
    epci = load_epci()
    isochrones = load_isochrones()
    
    # Create map
    m = folium.Map(
        location=[46.7, 2.5],
        zoom_start=6,
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='© OpenStreetMap'
    )
    
    # ---- EPCI Layer (colored by QPV count) ----
    if epci and qpv:
        # Count QPVs per EPCI
        qpv_counts = {}
        for f in qpv['features']:
            code = f.get('properties', {}).get('code_epci', '')
            if code:
                qpv_counts[code] = qpv_counts.get(code, 0) + 1
        
        # Add count to EPCI features
        for f in epci['features']:
            code = f['properties'].get('codgeo', '')
            f['properties']['qpv_count'] = qpv_counts.get(code, 0)
        
        # Filter to EPCIs with QPV
        epci_with_qpv = {
            'type': 'FeatureCollection',
            'features': [f for f in epci['features'] if f['properties']['qpv_count'] > 0]
        }
        
        if epci_with_qpv['features']:
            counts = sorted([f['properties']['qpv_count'] for f in epci_with_qpv['features']])
            colors = ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d']
            n = len(counts)
            breaks = [counts[min(int(n * i / 7), n-1)] for i in range(1, 7)]
            
            def get_epci_color(count):
                for i, b in enumerate(breaks):
                    if count <= b: return colors[i]
                return colors[-1]
            
            folium.GeoJson(
                epci_with_qpv,
                name='EPCI (nb QPV)',
                style_function=lambda f: {
                    'fillColor': get_epci_color(f['properties']['qpv_count']),
                    'color': '#666', 'weight': 0.5, 'fillOpacity': 0.5
                },
                tooltip=folium.GeoJsonTooltip(['libgeo', 'qpv_count'], ['EPCI:', 'QPV:']),
                show=False
            ).add_to(m)
    
    # ---- QPV Layer ----
    if qpv:
        folium.GeoJson(
            qpv,
            name='QPV',
            style_function=lambda f: {
                'fillColor': '#FFD700', 'color': '#FF8C00',
                'weight': 1, 'fillOpacity': 0.4
            },
            tooltip=folium.GeoJsonTooltip(['nom_qp'], ['QPV:']),
            show=False
        ).add_to(m)
    
    # ---- Isochrone Layers ----
    iso_configs = [
        ('driving', 10, '🚗 10 min', '#3388ff'),
        ('driving', 15, '🚗 15 min', '#2266dd'),
        ('driving', 30, '🚗 30 min', '#1155cc'),
        ('driving', 40, '🚗 40 min', '#0044bb'),
        ('driving', 45, '🚗 45 min', '#0033aa'),
        ('driving', 60, '🚗 60 min', '#002299'),
        ('walking', 10, '🚶 10 min', '#ff9900'),
        ('walking', 15, '🚶 15 min', '#ff6600'),
    ]
    
    for mode, minutes, name, color in iso_configs:
        layer = folium.FeatureGroup(name=name, show=False)
        for key, geojson in isochrones.items():
            if f"_{mode}_{minutes}min" in key and geojson:
                try:
                    folium.GeoJson(
                        geojson,
                        style_function=lambda x, c=color: {
                            'fillColor': c, 'color': c,
                            'weight': 1, 'fillOpacity': 0.15
                        }
                    ).add_to(layer)
                except:
                    pass
        layer.add_to(m)
    
    # ---- Establishment Markers ----
    markers = folium.FeatureGroup(name='Établissements', show=True)
    
    for _, row in df.iterrows():
        lat, lng = row['lat'], row['lng']
        title = str(row.get('title', 'Sans nom'))
        cat = row.get('categorie', '')
        color = CATEGORY_COLORS.get(cat, '#808080')
        main_cat = get_main_cat(cat)
        
        # SVG pin marker
        pin_svg = f'''
        <svg width="24" height="36" viewBox="0 0 24 36" xmlns="http://www.w3.org/2000/svg">
            <path fill="{color}" stroke="#333" stroke-width="1" 
                  d="M12 0C5.4 0 0 5.4 0 12c0 7.2 12 24 12 24s12-16.8 12-24c0-6.6-5.4-12-12-12z"/>
            <circle fill="white" cx="12" cy="12" r="4"/>
        </svg>
        '''
        
        icon = folium.DivIcon(
            html=f'<div style="transform:translate(-12px,-36px);">{pin_svg}</div>',
            icon_size=(24, 36),
            icon_anchor=(0, 0)
        )
        
        popup = f"<b>{title}</b><br><small>{main_cat}</small>"
        
        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup, max_width=250),
            tooltip=title,
            icon=icon
        ).add_to(markers)
    
    markers.add_to(m)
    
    # Layer control
    folium.LayerControl(collapsed=False, position='topright').add_to(m)
    
    # Return HTML
    return m._repr_html_()

# ============================================
# CSS
# ============================================

st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #C8102E 0%, #8B0000 100%);
        color: white;
        padding: 1.2rem 1.5rem;
        border-radius: 10px;
        margin-bottom: 1rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .main-header h1 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stSpinner {text-align: center;}
</style>
""", unsafe_allow_html=True)

# ============================================
# SIDEBAR
# ============================================

df = load_establishments()

with st.sidebar:
    st.markdown("### 📊 Statistiques")
    st.metric("Établissements", len(df))
    
    st.markdown("---")
    st.markdown("**Par catégorie**")
    for cat, color in MAIN_COLORS.items():
        count = len(df[df['categorie'].apply(get_main_cat) == cat])
        if count > 0:
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;">'
                f'<div style="width:12px;height:12px;background:{color};border-radius:50%;"></div>'
                f'{cat}: <b>{count}</b></div>',
                unsafe_allow_html=True
            )
    
    st.markdown("---")
    st.markdown("### 🗺️ Couches")
    st.markdown("""
    Utilisez le **panneau en haut à droite** de la carte pour afficher:
    - EPCI colorés par nb de QPV
    - Quartiers Prioritaires (QPV)
    - Isochrones 🚗 et 🚶
    """)
    
    st.markdown("---")
    st.markdown("### 🎨 Légende")
    st.markdown("**Marqueurs**")
    legend = [
        ("Formation", "#4169e1"),
        ("Protection", "#dc143c"),
        ("Insertion", "#32cd32"),
        ("Parentalité", "#9370db"),
    ]
    for name, color in legend:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:6px;font-size:0.85rem;">'
            f'<div style="width:10px;height:10px;background:{color};border-radius:50%;"></div>'
            f'{name}</div>',
            unsafe_allow_html=True
        )

# ============================================
# MAIN CONTENT
# ============================================

st.markdown("""
<div class="main-header">
    <h1>🏠 Carte des établissements - Apprentis d'Auteuil</h1>
</div>
""", unsafe_allow_html=True)

# Build and display map (cached HTML - instant for all users after first load)
with st.spinner("Chargement de la carte..."):
    map_html = build_map_html()

# Display map as HTML - NO WebSocket traffic, pure JavaScript interactions
components.html(map_html, height=680, scrolling=False)

# Footer
st.caption("Carte interactive · Utilisez le panneau en haut à droite pour afficher/masquer les couches")
