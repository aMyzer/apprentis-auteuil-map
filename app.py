import streamlit as st

# Page configuration - MUST be the first Streamlit command
st.set_page_config(
    page_title="Outil de dataviz - Apprentis d'Auteuil",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

import streamlit.components.v1 as components
import folium
import pandas as pd
import json
import os

# Script directory for data files
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================
# HELPER FUNCTIONS (data loading)
# ============================================

def is_france_hexagonale(dept_code):
    """Check if department is in mainland France (not overseas)"""
    if not dept_code:
        return False
    return len(dept_code) <= 2 or dept_code.startswith('2')  # 2A, 2B for Corsica

@st.cache_resource
def load_qpv_geojson():
    """Load QPV geojson with caching - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "QP2024_France_Hexagonale_Outre_Mer_WGS84.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['features'] = [
            f for f in data['features'] 
            if is_france_hexagonale(f.get('properties', {}).get('insee_dep'))
        ]
        return data
    return None

@st.cache_resource
def load_epci_geojson():
    """Load EPCI boundaries geojson with caching - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "epci_2025_complete.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        overseas_code_prefixes = ['24971', '24972', '24973', '24974', '24976', '249720', '249730', '249740']
        data['features'] = [
            f for f in data['features']
            if not any(str(f.get('properties', {}).get('codgeo', '')).startswith(prefix) for prefix in overseas_code_prefixes)
        ]
        return data
    return None

@st.cache_resource
def load_isochrone_cache():
    """Load isochrone cache from file"""
    cache_path = os.path.join(SCRIPT_DIR, "isochrone_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

@st.cache_resource
def load_default_data():
    """Load the categorized CSV file with caching"""
    csv_path = os.path.join(SCRIPT_DIR, "Draft etablissements_categorized.csv")
    df = pd.read_csv(csv_path, encoding='utf-8')
    df = df.dropna(subset=['lat', 'lng'])
    # Filter to mainland France
    df = df[(df['lat'] >= 41) & (df['lat'] <= 52) & (df['lng'] >= -6) & (df['lng'] <= 10)]
    return df

@st.cache_resource
def load_indicator_data(filename):
    """Load indicator CSV file"""
    csv_path = os.path.join(SCRIPT_DIR, filename)
    if os.path.exists(csv_path):
        return pd.read_csv(csv_path, encoding='utf-8')
    return None

# ============================================
# CATEGORY COLORS
# ============================================

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

MAIN_CATEGORY_COLORS = {
    "Formation": "#4169e1",
    "Protection de l'enfance": "#dc143c",
    "Insertion": "#32cd32",
    "Parentalité": "#9370db",
}

def get_main_category(categorie):
    """Extract main category from full category string"""
    if pd.isna(categorie) or categorie == '':
        return "Inconnu"
    if "Formation" in categorie:
        return "Formation"
    elif "Protection" in categorie:
        return "Protection de l'enfance"
    elif "Insertion" in categorie or "Inserttion" in categorie:
        return "Insertion"
    elif "Parental" in categorie or "Parent" in categorie:
        return "Parentalité"
    return "Inconnu"

# ============================================
# BUILD MAP HTML (CACHED - THE KEY FUNCTION)
# ============================================

@st.cache_resource
def build_map_html():
    """Build the entire map and return HTML - cached across all sessions"""
    
    # Load data
    df = load_default_data()
    qpv_data = load_qpv_geojson()
    epci_data = load_epci_geojson()
    isochrone_cache = load_isochrone_cache()
    
    # Create map
    m = folium.Map(location=[46.7, 2.5], zoom_start=6, tiles=None)
    
    # Add OpenStreetMap tiles
    folium.TileLayer(
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='© OpenStreetMap',
        name='OpenStreetMap',
        max_zoom=19
    ).add_to(m)
    
    # ---- EPCI Layer with QPV count ----
    if epci_data and qpv_data:
        # Count QPVs per EPCI
        epci_qpv_counts = {}
        for qpv in qpv_data['features']:
            epci_code = qpv.get('properties', {}).get('code_epci', '')
            if epci_code:
                epci_qpv_counts[epci_code] = epci_qpv_counts.get(epci_code, 0) + 1
        
        # Add count to EPCI features
        for feature in epci_data['features']:
            code = feature.get('properties', {}).get('codgeo', '')
            feature['properties']['qpv_count'] = epci_qpv_counts.get(code, 0)
        
        # Filter to EPCIs with QPV > 0
        filtered_epci = {
            'type': 'FeatureCollection',
            'features': [f for f in epci_data['features'] if f['properties']['qpv_count'] > 0]
        }
        
        if filtered_epci['features']:
            qpv_counts = sorted([f['properties']['qpv_count'] for f in filtered_epci['features']])
            colors = ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d']
            n = len(qpv_counts)
            breaks = [qpv_counts[min(int(n * i / len(colors)), n-1)] for i in range(1, len(colors))]
            
            def get_color(count):
                for i, threshold in enumerate(breaks):
                    if count <= threshold:
                        return colors[i]
                return colors[-1]
            
            folium.GeoJson(
                filtered_epci,
                name='EPCI par nb QPV',
                style_function=lambda f: {
                    'fillColor': get_color(f['properties']['qpv_count']),
                    'color': '#666',
                    'weight': 0.5,
                    'fillOpacity': 0.6
                },
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'qpv_count'], aliases=['EPCI:', 'Nb QPV:']),
                show=False
            ).add_to(m)
    
    # ---- QPV Layer ----
    if qpv_data:
        folium.GeoJson(
            qpv_data,
            name='QPV',
            style_function=lambda f: {'fillColor': '#FFD700', 'color': '#FF8C00', 'weight': 1, 'fillOpacity': 0.4},
            tooltip=folium.GeoJsonTooltip(fields=['nom_qp'], aliases=['QPV:']),
            show=False
        ).add_to(m)
    
    # ---- Indicator Layers ----
    def add_indicator_layer(indicator_name, csv_file, column, layer_name, colors):
        """Add a choropleth indicator layer"""
        indicator_df = load_indicator_data(csv_file)
        if indicator_df is None or epci_data is None:
            return
        
        # Create EPCI code to value mapping
        value_map = {}
        for _, row in indicator_df.iterrows():
            code = str(row.get('CODGEO', '')).zfill(9)
            val = row.get(column)
            if pd.notna(val):
                value_map[code] = float(val)
        
        if not value_map:
            return
        
        # Create filtered GeoJSON with values
        features_with_data = []
        for f in epci_data['features']:
            code = str(f['properties'].get('codgeo', '')).zfill(9)
            if code in value_map:
                f_copy = json.loads(json.dumps(f))  # Deep copy
                f_copy['properties']['indicator_value'] = value_map[code]
                features_with_data.append(f_copy)
        
        if not features_with_data:
            return
        
        # Calculate quantile breaks
        values = sorted([f['properties']['indicator_value'] for f in features_with_data])
        n = len(values)
        breaks = [values[min(int(n * i / len(colors)), n-1)] for i in range(1, len(colors))]
        
        def get_indicator_color(val):
            for i, threshold in enumerate(breaks):
                if val <= threshold:
                    return colors[i]
            return colors[-1]
        
        geojson_data = {'type': 'FeatureCollection', 'features': features_with_data}
        
        folium.GeoJson(
            geojson_data,
            name=layer_name,
            style_function=lambda f: {
                'fillColor': get_indicator_color(f['properties']['indicator_value']),
                'color': '#666',
                'weight': 0.5,
                'fillOpacity': 0.6
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'indicator_value'],
                aliases=['EPCI:', f'{indicator_name}:']
            ),
            show=False
        ).add_to(m)
    
    # Add indicator layers
    blue_colors = ['#f7fbff', '#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c']
    add_indicator_layer('Taux chômage', 'taux_chomage_epci.csv', 'T', 'Taux chômage (INSEE) 2022', blue_colors)
    add_indicator_layer('Taux pauvreté', 'taux_pauvrete_epci.csv', 'T', 'Taux pauvreté (INSEE) 2022', blue_colors)
    add_indicator_layer('Part NEETs', '15-24_neets_epci.csv', 'T', 'Part NEETs 15-24 (INSEE) 2022', blue_colors)
    add_indicator_layer('Sans diplôme', '15+_sans_diplomes_epci.csv', 'T', 'Part +15 ans sans diplôme (INSEE) 2022', blue_colors)
    
    # ---- Isochrone Layers ----
    isochrone_configs = [
        ('driving', 10, '🚗 10 min'),
        ('driving', 15, '🚗 15 min'),
        ('driving', 30, '🚗 30 min'),
        ('driving', 40, '🚗 40 min'),
        ('driving', 45, '🚗 45 min'),
        ('driving', 60, '🚗 60 min'),
        ('walking', 10, '🚶 10 min'),
        ('walking', 15, '🚶 15 min'),
    ]
    
    iso_colors = {'driving': '#3388ff', 'walking': '#ff7800'}
    
    for mode, minutes, layer_name in isochrone_configs:
        features = []
        for key, geojson in isochrone_cache.items():
            if f"_{mode}_{minutes}min" in key and geojson:
                if isinstance(geojson, dict) and 'features' in geojson:
                    features.extend(geojson['features'])
                elif isinstance(geojson, dict) and 'geometry' in geojson:
                    features.append(geojson)
        
        if features:
            layer = folium.FeatureGroup(name=layer_name, show=False)
            for feature in features:
                try:
                    folium.GeoJson(
                        feature,
                        style_function=lambda f, c=iso_colors[mode]: {
                            'fillColor': c,
                            'color': c,
                            'weight': 1,
                            'fillOpacity': 0.2
                        }
                    ).add_to(layer)
                except:
                    pass
            layer.add_to(m)
    
    # ---- Establishment Markers ----
    markers_layer = folium.FeatureGroup(name='Établissements', show=True)
    
    for _, row in df.iterrows():
        lat, lng = row['lat'], row['lng']
        title = row.get('title', 'Sans nom')
        categorie = row.get('categorie', '')
        caracterisation = row.get('caracterisation', '')
        
        main_cat = get_main_category(categorie)
        marker_color = CATEGORY_COLORS.get(categorie, "#808080")
        
        # Create popup
        popup_html = f"<b>{title}</b><br><small>{main_cat}</small>"
        if caracterisation:
            popup_html += f"<br><i>{caracterisation[:100]}...</i>" if len(str(caracterisation)) > 100 else f"<br><i>{caracterisation}</i>"
        
        # Create custom pin with SVG
        pin_html = f'''
        <div style="position:relative;">
            <svg width="25" height="41" viewBox="0 0 25 41" xmlns="http://www.w3.org/2000/svg">
                <path fill="{marker_color}" stroke="#333" stroke-width="1" d="M12.5 0C5.6 0 0 5.6 0 12.5c0 2.4.7 4.7 1.9 6.6L12.5 41l10.6-21.9c1.2-1.9 1.9-4.2 1.9-6.6C25 5.6 19.4 0 12.5 0z"/>
                <circle fill="white" cx="12.5" cy="12.5" r="5"/>
            </svg>
        </div>
        '''
        
        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"{title} | {main_cat}",
            icon=folium.DivIcon(html=pin_html, icon_size=(25, 41), icon_anchor=(12, 41))
        ).add_to(markers_layer)
    
    markers_layer.add_to(m)
    
    # Add layer control
    folium.LayerControl(collapsed=False, position='topright').add_to(m)
    
    # Return HTML
    return m._repr_html_()

# ============================================
# CSS STYLING
# ============================================

st.markdown("""
<style>
    /* Main title styling */
    .main-title {
        background-color: #C8102E;
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        font-size: 1.3rem;
        font-weight: 600;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    
    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background-color: #f8f9fa;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# SIDEBAR
# ============================================

df = load_default_data()

with st.sidebar:
    st.markdown("### 🎨 Légende des établissements")
    
    legend_groups = {
        "Formation": [
            ("1er deg", "Formation : 1ier deg"),
            ("Collège", "Formation : College"),
            ("Lycée pro", "Formation : Lycee pro"),
            ("Lycée pro agricole", "Formation : Lycee pro agricole"),
            ("Post-bac", "Formation : Post-bac"),
        ],
        "Protection de l'enfance": [
            ("MECs MNA", "Protection de l'enfance : MECs MNA"),
            ("MECs Fratrie", "Protection de l'enfance : MECs Fratrie"),
            ("MECs AEMO", "Protection de l'enfance : MECs AEMO"),
            ("MECs Semi-autonomie", "Protection de l'enfance : MECs Semi autnomie"),
        ],
        "Insertion": [
            ("Dispo insertion", "Insertion: Dispo insertion"),
            ("IAE", "Inserttion : IAE"),
        ],
        "Parentalité": [
            ("Maison des familles", "Parentialité : Maison des familles"),
            ("Crèches", "Parentalité : Creches"),
            ("Autres dispositifs", "Parentalité : Autres dispositifs parentalité"),
        ],
    }
    
    for main_cat, subcats in legend_groups.items():
        st.markdown(f"**{main_cat}**")
        for short_name, full_cat in subcats:
            color = CATEGORY_COLORS.get(full_cat, "#808080")
            st.markdown(
                f'<div style="display:flex;align-items:center;margin:2px 0 2px 10px;">'
                f'<div style="width:14px;height:14px;border-radius:50%;background:{color};margin-right:6px;border:1px solid #333;"></div>'
                f'<span style="font-size:11px;">{short_name}</span></div>',
                unsafe_allow_html=True
            )
    
    st.markdown("---")
    
    # Category statistics
    st.markdown("### 📊 Par catégorie")
    if 'categorie' in df.columns:
        cat_counts = df['categorie'].apply(get_main_category).value_counts()
        for cat, count in cat_counts.items():
            color = MAIN_CATEGORY_COLORS.get(cat, "#808080")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;">'
                f'<div style="width:12px;height:12px;background:{color};border-radius:50%;"></div>'
                f'<span style="font-size:0.85rem;">{cat}: <strong>{count}</strong></span></div>',
                unsafe_allow_html=True
            )
    
    st.caption(f"**Total: {len(df)} établissements**")
    
    st.markdown("---")
    
    st.markdown("""
    **Couches disponibles** (panneau carte ↗)
    - EPCI colorés par nb QPV
    - Quartiers prioritaires (QPV)
    - Indicateurs INSEE 2022
    - Zones d'accessibilité (isochrones)
    """)

# ============================================
# MAIN CONTENT
# ============================================

st.markdown('<div class="main-title">🏠 Outil de dataviz pour les Apprentis d\'Auteuil</div>', unsafe_allow_html=True)

# Build and display the map (cached HTML)
with st.spinner('Chargement de la carte...'):
    map_html = build_map_html()

# Display the map
components.html(map_html, height=700, scrolling=False)

# Help section
with st.expander("❓ Aide", expanded=False):
    st.markdown("""
    **Navigation carte**
    - Molette = zoom
    - Glisser = déplacer
    - Clic marqueur = détails
    
    **Couches** (panneau en haut à droite)
    - Cochez/décochez pour afficher/masquer
    - QPV, EPCI, indicateurs INSEE
    - Zones d'accessibilité 🚗 et 🚶
    
    **Marqueurs**
    - 🔵 Bleu = Formation
    - 🔴 Rouge = Protection de l'enfance
    - 🟢 Vert = Insertion
    - 🟣 Violet = Parentalité
    """)
