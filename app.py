import streamlit as st

# Page configuration - MUST be the first Streamlit command
st.set_page_config(
    page_title="Outil de dataviz - Apprentis d'Auteuil",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

import folium
import streamlit.components.v1 as components
import pandas as pd
import io
import json
import os
import requests
import time

# Mapbox API token from secrets (for on-demand isochrone calls)
# Token is optional - isochrones are pre-cached in isochrone_cache.json
try:
    MAPBOX_TOKEN = st.secrets["MAPBOX_TOKEN"]
except Exception:
    MAPBOX_TOKEN = ""

# Initialize API logs in session state
if 'api_logs' not in st.session_state:
    st.session_state.api_logs = []

def add_log(message, level="info"):
    """Add a log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    st.session_state.api_logs.append({"time": timestamp, "level": level, "msg": message})
    # Keep only last 50 logs
    if len(st.session_state.api_logs) > 50:
        st.session_state.api_logs = st.session_state.api_logs[-50:]

# Cache file for isochrones (in same directory as script)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ISOCHRONE_CACHE_FILE = os.path.join(SCRIPT_DIR, "isochrone_cache.json")

def load_isochrone_cache():
    """Load isochrone cache from file"""
    if os.path.exists(ISOCHRONE_CACHE_FILE):
        try:
            with open(ISOCHRONE_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_isochrone_cache(cache):
    """Save isochrone cache to file"""
    try:
        with open(ISOCHRONE_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        return True
    except Exception as e:
        add_log(f"✗ Save failed: {str(e)[:50]}", "error")
        return False

def is_france_hexagonale(dept_code):
    """Check if department is in mainland France (not overseas)"""
    if not dept_code:
        return False
    # Overseas departments start with 97 and are 3 digits
    return len(dept_code) <= 2 or dept_code.startswith('2')  # 2A, 2B for Corsica

# Cache version for forcing refresh when code changes
CACHE_VERSION = "v1.0"

@st.cache_resource
def load_qpv_geojson(_version=CACHE_VERSION):
    """Load QPV geojson with caching - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "QP2024_France_Hexagonale_Outre_Mer_WGS84.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Filter to mainland France only
        data['features'] = [
            f for f in data['features'] 
            if is_france_hexagonale(f.get('properties', {}).get('insee_dep'))
        ]
        
        # Simplify coordinates to reduce file size and improve rendering speed
        # 3 decimal places (~110m precision) - good for visualization
        def simplify_coords(coords, precision=3):
            if isinstance(coords[0], (int, float)):
                return [round(c, precision) for c in coords]
            return [simplify_coords(c, precision) for c in coords]
        
        for feature in data['features']:
            if 'geometry' in feature and 'coordinates' in feature['geometry']:
                feature['geometry']['coordinates'] = simplify_coords(feature['geometry']['coordinates'])
        
        return data
    return None

@st.cache_resource
def load_epci_geojson(_version=CACHE_VERSION):
    """Load EPCI boundaries geojson with caching - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "epci_2025_complete.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # Overseas keywords to exclude (some have bad coordinates in GeoJSON)
        overseas_keywords = ['Guadeloupe', 'Martinique', 'Guyane', 'Mayotte', 'Réunion', 
                            'Reunion', 'Levant', 'Saint-Martin', 'Saint-Pierre',
                            'Basse-Terre', 'Caraïbe', 'Caraibe', 'Cara\xefbe', 'Cap Excellence',
                            'Grande-Terre', 'Marie-Galante', 'Savanes', 'Dembeni', 'Petite-Terre',
                            'Centre Ouest', 'Nord Grande']
        
        # Exact EPCI names to exclude (overseas with generic names)
        overseas_exact_names = ['CC du Sud', 'CC du Centre Ouest', 'CC du Centre-Ouest']
        
        # Also filter by EPCI code patterns (971x = Guadeloupe, 972x = Martinique, etc.)
        # Note: Removed '20004' as it incorrectly filtered 121 mainland EPCIs including Lyon Métropole
        overseas_code_prefixes = ['24971', '24972', '24973', '24974', '24976', '249720', '249730', '249740']  # DOM codes
        
        def is_overseas_name(name):
            """Check if EPCI name contains overseas territory keyword or is exact match"""
            if not name:
                return False
            # Check exact matches first
            if name in overseas_exact_names:
                return True
            name_lower = name.lower()
            return any(kw.lower() in name_lower for kw in overseas_keywords)
        
        def is_overseas_code(code):
            """Check if EPCI code starts with overseas prefix"""
            if not code:
                return False
            return any(code.startswith(prefix) for prefix in overseas_code_prefixes)
        
        # Filter by bounding box AND exclude overseas names/codes
        def in_mainland(feature):
            props = feature.get('properties', {})
            # Check name - some overseas have bad coords
            name = props.get('libgeo', '')
            if is_overseas_name(name):
                return False
            # Check code prefix
            code = props.get('codgeo', '')
            if is_overseas_code(code):
                return False
            
            coords = feature.get('geometry', {}).get('coordinates', [])
            if not coords:
                return False
            # Get first coordinate to check location
            try:
                # Handle Polygon and MultiPolygon
                geom_type = feature.get('geometry', {}).get('type')
                if geom_type == 'Polygon':
                    lng, lat = coords[0][0][0], coords[0][0][1]
                elif geom_type == 'MultiPolygon':
                    lng, lat = coords[0][0][0][0], coords[0][0][0][1]
                else:
                    return True
                return -6 < lng < 10 and 41 < lat < 52
            except (IndexError, TypeError):
                return True
        
        data['features'] = [f for f in data['features'] if in_mainland(f)]
        
        # Simplify coordinates to reduce file size and improve rendering speed
        # Round to 3 decimal places (~110 meters precision) - good enough for visualization
        def simplify_coords(coords, precision=3):
            if isinstance(coords[0], (int, float)):
                return [round(c, precision) for c in coords]
            return [simplify_coords(c, precision) for c in coords]
        
        for feature in data['features']:
            if 'geometry' in feature and 'coordinates' in feature['geometry']:
                feature['geometry']['coordinates'] = simplify_coords(feature['geometry']['coordinates'])
        
        return data
    return None

@st.cache_resource
def get_mainland_epci_codes(_version=CACHE_VERSION):
    """Get set of EPCI codes from mainland France GeoJSON (source of truth)"""
    epci_data = load_epci_geojson()
    if epci_data:
        return set(f['properties']['codgeo'] for f in epci_data['features'])
    return set()

@st.cache_resource
def get_mainland_epci_names(_version=CACHE_VERSION):
    """Get set of EPCI names from mainland France GeoJSON (source of truth)"""
    import unicodedata
    def normalize_name(name):
        if not isinstance(name, str):
            return ''
        nfkd = unicodedata.normalize('NFKD', name)
        ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return ascii_name.lower().strip()
    
    epci_data = load_epci_geojson()
    if epci_data:
        return set(normalize_name(f['properties']['libgeo']) for f in epci_data['features'])
    return set()

@st.cache_resource
def load_chomage_epci(_version=CACHE_VERSION):
    """Load unemployment rate by EPCI (F=female, H=male, T=total) - mainland France only"""
    csv_path = os.path.join(SCRIPT_DIR, "taux_chomage_epci.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        df = pd.read_csv(csv_path)
        
        # Convert codgeo to string for matching
        df['codgeo'] = df['codgeo'].astype(str)
        
        # Filter to only EPCIs that exist in mainland France GeoJSON
        valid_codes = get_mainland_epci_codes()
        df = df[df['codgeo'].isin(valid_codes)]
        
        # Pivot to get F, H, T columns per EPCI
        pivot = df.pivot(index='codgeo', columns='sexe', values='tx_chom1564').reset_index()
        pivot.columns = ['codgeo', 'chomage_F', 'chomage_H', 'chomage_T']
        # Add EPCI name from original data
        names = df[['codgeo', 'libgeo']].drop_duplicates()
        pivot = pivot.merge(names, on='codgeo', how='left')
        return pivot.set_index('codgeo').to_dict('index')
    return {}

@st.cache_resource
def load_pauvrete_epci():
    """Load poverty rate by EPCI (matched by name) - mainland France only"""
    csv_path = os.path.join(SCRIPT_DIR, "taux_pauvrete_epci.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        import unicodedata
        
        def normalize_name(name):
            """Normalize EPCI name for matching (remove accents, lowercase, strip)"""
            if not isinstance(name, str):
                return ''
            # Normalize unicode, remove accents
            nfkd = unicodedata.normalize('NFKD', name)
            ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
            return ascii_name.lower().strip()
        
        df = pd.read_csv(csv_path)
        # Rename columns for easier handling
        df.columns = ['libgeo', 'taux_pauvrete']
        
        df['libgeo_normalized'] = df['libgeo'].apply(normalize_name)
        
        # Filter to only EPCIs that exist in mainland France GeoJSON
        valid_names = get_mainland_epci_names()
        df = df[df['libgeo_normalized'].isin(valid_names)]
        
        # Drop duplicates (keep first occurrence)
        df = df.drop_duplicates(subset='libgeo_normalized', keep='first')
        # Return dict keyed by normalized EPCI name
        return df.set_index('libgeo_normalized').to_dict('index')
    return {}

@st.cache_resource
def load_neets_epci(_version=CACHE_VERSION):
    """Load NEETs rate (15-24 not in education/employment) by EPCI - mainland France only"""
    csv_path = os.path.join(SCRIPT_DIR, "15-24_neets_epci.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        df = pd.read_csv(csv_path)
        
        # Convert codgeo to string for matching
        df['codgeo'] = df['codgeo'].astype(str)
        
        # Filter to only EPCIs that exist in mainland France GeoJSON
        valid_codes = get_mainland_epci_codes()
        df = df[df['codgeo'].isin(valid_codes)]
        
        return df.set_index('codgeo').to_dict('index')
    return {}

@st.cache_resource
def load_sans_diplome_epci(_version=CACHE_VERSION):
    """Load % without diploma (15+) by EPCI (F=female, H=male, T=total) - mainland France only"""
    csv_path = os.path.join(SCRIPT_DIR, "15+_sans_diplomes_epci.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        df = pd.read_csv(csv_path)
        
        # Convert codgeo to string for matching
        df['codgeo'] = df['codgeo'].astype(str)
        
        # Filter to only EPCIs that exist in mainland France GeoJSON
        valid_codes = get_mainland_epci_codes()
        df = df[df['codgeo'].isin(valid_codes)]
        
        # Pivot to get F, H, T columns per EPCI
        pivot = df.pivot(index='codgeo', columns='sexe', values='p_nondipl15').reset_index()
        pivot.columns = ['codgeo', 'sans_diplome_F', 'sans_diplome_H', 'sans_diplome_T']
        # Add EPCI name from original data
        names = df[['codgeo', 'libgeo']].drop_duplicates()
        pivot = pivot.merge(names, on='codgeo', how='left')
        return pivot.set_index('codgeo').to_dict('index')
    return {}

@st.cache_resource
def get_epci_with_indicators(_version=CACHE_VERSION):
    """Load EPCI GeoJSON enriched with all indicators"""
    import unicodedata
    import copy
    
    def normalize_name(name):
        """Normalize EPCI name for matching (remove accents, lowercase, strip)"""
        if not isinstance(name, str):
            return ''
        nfkd = unicodedata.normalize('NFKD', name)
        ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
        return ascii_name.lower().strip()
    
    qpv_data = load_qpv_geojson()
    epci_data_original = load_epci_geojson()
    chomage_data = load_chomage_epci()
    pauvrete_data = load_pauvrete_epci()
    neets_data = load_neets_epci()
    sans_diplome_data = load_sans_diplome_epci()
    
    # Deep copy to avoid mutating cached data
    if not epci_data_original:
        return None
    epci_data = copy.deepcopy(epci_data_original)
    
    # Count QPVs per EPCI
    qpv_counts = {}
    if qpv_data:
        for feature in qpv_data.get('features', []):
            siren_epci = feature.get('properties', {}).get('siren_epci')
            if siren_epci:
                qpv_counts[siren_epci] = qpv_counts.get(siren_epci, 0) + 1
    
    # Enrich EPCI features with all indicators
    for feature in epci_data.get('features', []):
        codgeo = feature.get('properties', {}).get('codgeo')
        libgeo = feature.get('properties', {}).get('libgeo')
        libgeo_norm = normalize_name(libgeo)
        # Add QPV count
        feature['properties']['qpv_count'] = qpv_counts.get(codgeo, 0)
        # Add unemployment data (F, H, T) - matched by code
        if codgeo in chomage_data:
            ch = chomage_data[codgeo]
            feature['properties']['chomage_F'] = ch.get('chomage_F')
            feature['properties']['chomage_H'] = ch.get('chomage_H')
            feature['properties']['chomage_T'] = ch.get('chomage_T')
        # Add poverty data - matched by normalized name
        if libgeo_norm in pauvrete_data:
            feature['properties']['taux_pauvrete'] = pauvrete_data[libgeo_norm].get('taux_pauvrete')
        # Add NEETs data - matched by code
        if codgeo in neets_data:
            feature['properties']['neets'] = neets_data[codgeo].get('part_non_inseres')
        # Add sans diplôme data (F, H, T) - matched by code
        if codgeo in sans_diplome_data:
            sd = sans_diplome_data[codgeo]
            feature['properties']['sans_diplome_F'] = sd.get('sans_diplome_F')
            feature['properties']['sans_diplome_H'] = sd.get('sans_diplome_H')
            feature['properties']['sans_diplome_T'] = sd.get('sans_diplome_T')
    
    return epci_data

@st.cache_resource
def get_epci_qpv_counts(_version=CACHE_VERSION):
    """Count QPVs per EPCI and return enriched EPCI geojson"""
    import copy
    qpv_data = load_qpv_geojson()
    epci_data_original = load_epci_geojson()
    
    if not qpv_data or not epci_data_original:
        return None
    
    # Deep copy to avoid mutating cached data
    epci_data = copy.deepcopy(epci_data_original)
    
    # Count QPVs per EPCI
    qpv_counts = {}
    for feature in qpv_data.get('features', []):
        siren_epci = feature.get('properties', {}).get('siren_epci')
        if siren_epci:
            qpv_counts[siren_epci] = qpv_counts.get(siren_epci, 0) + 1
    
    # Add QPV count to each EPCI feature
    for feature in epci_data.get('features', []):
        codgeo = feature.get('properties', {}).get('codgeo')
        feature['properties']['qpv_count'] = qpv_counts.get(codgeo, 0)
    
    return epci_data

# Page configuration is set at the top of the file

# ============================================
# CUSTOM CSS - APPRENTIS D'AUTEUIL BRANDING
# ============================================
st.markdown("""
<style>
    /* Import Inter font */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
    
    /* CSS Variables - Apprentis d'Auteuil palette */
    :root {
        --main: #db052b;
        --main-dark: #b51531;
        --white: #ffffff;
        --grey: #383838;
        --grey-light: #656565;
        --grey-10: #d8d8d8;
        --warm-01: #f5f6eb;
        --warm-02: #d4ccbe;
        --beige-01: #f5f6eb;
        --beige-02: #e1dbd0;
        --yellow-01: #fad663;
        --yellow-02: #d1ab47;
    }
    
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Main container - minimal padding */
    .main .block-container {
        padding-top: 0rem;
        padding-bottom: 0.3rem;
        max-width: 100%;
    }
    
    /* Compact header bar */
    .header-bar {
        background: var(--main);
        padding: 0.4rem 1rem;
        border-radius: 3px;
        margin-bottom: 0.4rem;
        display: flex;
        align-items: center;
        gap: 0.8rem;
    }
    
    .header-bar h1 {
        color: var(--white);
        margin: 0;
        font-family: 'Inter', sans-serif;
        font-size: 0.95rem;
        font-weight: 700;
        letter-spacing: -0.02em;
    }
    
    .header-bar .subtitle {
        color: rgba(255,255,255,0.85);
        font-size: 0.75rem;
        font-family: 'Inter', sans-serif;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background-color: var(--warm-01);
        border-right: 1px solid var(--beige-02);
        min-width: 280px !important;
        max-width: 280px !important;
        width: 280px !important;
    }
    
    [data-testid="stSidebar"] > div:first-child {
        width: 280px !important;
    }
    
    [data-testid="stSidebar"] .block-container {
        padding-top: 0rem;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    
    /* Sidebar headers */
    [data-testid="stSidebar"] h3 {
        font-family: 'Inter', sans-serif;
        font-size: 0.8rem;
        font-weight: 700;
        color: var(--grey);
        margin-top: 0.3rem;
        margin-bottom: 0.4rem;
        padding-bottom: 0.3rem;
        border-bottom: 2px solid var(--main);
    }
    
    /* Age group filter with rectangle color */
    .age-filter-item {
        display: flex;
        align-items: center;
        padding: 0.3rem 0.5rem;
        margin: 0.2rem 0;
        border-radius: 3px;
        background: var(--white);
        border: 1px solid var(--beige-02);
        transition: all 0.2s ease;
    }
    
    .age-filter-item:hover {
        border-color: var(--main);
        box-shadow: 0 2px 4px rgba(219, 5, 43, 0.1);
    }
    
    .color-rect {
        width: 18px;
        height: 12px;
        border-radius: 2px;
        margin-right: 8px;
        flex-shrink: 0;
        border: 1px solid rgba(0,0,0,0.1);
    }
    
    /* Stats styling */
    .stat-box {
        background: var(--white);
        padding: 0.4rem;
        border-radius: 3px;
        text-align: center;
        border: 1px solid var(--beige-02);
    }
    
    .stat-box .number {
        font-family: 'Inter', sans-serif;
        font-size: 1.2rem;
        font-weight: 700;
        color: var(--main);
        line-height: 1;
    }
    
    .stat-box .label {
        font-size: 0.65rem;
        color: var(--grey-light);
        margin-top: 0.15rem;
    }
    
    /* Map container */
    .map-container {
        border-radius: 4px;
        overflow: hidden;
        box-shadow: 0 2px 6px rgba(0,0,0,0.08);
        border: 1px solid var(--beige-02);
        margin-top: 0.2rem;
    }
    
    /* Button styling */
    .stButton > button {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        border-radius: 4px;
        transition: all 0.2s ease;
    }
    
    .stButton > button[kind="primary"] {
        background-color: var(--main);
        border-color: var(--main);
    }
    
    .stButton > button[kind="primary"]:hover {
        background-color: var(--main-dark);
        border-color: var(--main-dark);
    }
    
    /* Slider styling */
    .stSlider > div > div > div {
        background-color: var(--main);
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.8rem;
        background-color: var(--white);
        border: 1px solid var(--beige-02);
        border-radius: 3px;
        padding: 0.4rem 0.6rem !important;
    }
    
    /* Remove extra spacing */
    .element-container {
        margin-bottom: 0.3rem;
    }
    
    /* Tighter markdown spacing */
    .stMarkdown p {
        margin-bottom: 0.3rem;
        font-size: 0.8rem;
    }
    
    .stMarkdown h3 {
        margin-top: 0.3rem;
        margin-bottom: 0.3rem;
    }
    
    /* Horizontal rule spacing */
    hr {
        margin: 0.4rem 0 !important;
    }
    
    /* File uploader */
    [data-testid="stFileUploader"] {
        padding: 0.5rem;
        background: var(--white);
        border-radius: 4px;
        border: 1px dashed var(--beige-02);
    }
    
    /* Metrics */
    [data-testid="stMetric"] {
        background: var(--white);
        padding: 0.35rem 0.4rem;
        border-radius: 3px;
        border: 1px solid var(--beige-02);
    }
    
    [data-testid="stMetric"] label {
        font-size: 0.65rem !important;
        font-family: 'Inter', sans-serif !important;
    }
    
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-size: 1.1rem !important;
        font-family: 'Inter', sans-serif !important;
        color: var(--main) !important;
        font-weight: 700 !important;
    }
    
    /* Checkbox styling */
    .stCheckbox label {
        font-family: 'Inter', sans-serif;
        font-size: 0.75rem;
    }
    
    /* Number input styling */
    [data-testid="stNumberInput"] input {
        font-size: 0.7rem !important;
        font-family: 'Inter', sans-serif !important;
        padding: 0.2rem 0.3rem !important;
    }
    
    [data-testid="stNumberInput"] label {
        font-size: 0.7rem !important;
    }
    
    /* Info/Help sections */
    .stAlert {
        border-radius: 4px;
        border: none;
        font-family: 'Inter', sans-serif;
    }
    
    /* Data editor */
    [data-testid="stDataFrame"] {
        border: 1px solid var(--beige-02);
        border-radius: 4px;
    }
    
    /* Hide ALL sidebar collapse/expand buttons */
    section[data-testid="stSidebar"] button[kind="header"],
    section[data-testid="stSidebar"] [data-testid="baseButton-header"],
    section[data-testid="stSidebar"] [data-testid="collapsedControl"],
    [data-testid="collapsedControl"] {
        display: none !important;
        visibility: hidden !important;
    }
    
    /* Ensure sidebar is always visible and locked */
    section[data-testid="stSidebar"] {
        display: block !important;
        pointer-events: auto !important;
    }
    
    section[data-testid="stSidebar"][aria-expanded="false"] {
        display: block !important;
        transform: none !important;
    }
    
    /* Custom metric with icon */
    .metric-with-icon {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 0.3rem;
        font-size: 1.1rem;
        font-weight: 700;
        color: var(--main);
    }
    
    .gold-star-icon {
        font-size: 1rem;
        color: #FF8C00;
    }
</style>
""", unsafe_allow_html=True)

# ============================================
# COMPACT HEADER
# ============================================
st.markdown("""
<div class="header-bar">
    <h1>🏠 Outil de dataviz pour les Apprentis d'Auteuil</h1>
</div>
""", unsafe_allow_html=True)

# ============================================
# DATA LOADING WITH CACHING
# ============================================

# Age group configurations
age_group_priority = [
    "Très petits (0-6 ans)",
    "Petits (5-11 ans)",
    "Moyens (10-15 ans)",
    "Grands (14-18 ans)",
    "Jeunes Adultes (17-21 ans)",
    "Adultes (sup 21 ans)"
]

age_groups = {
    "Très petits (0-6 ans)": {
        "default": 1.0,
        "color": "#8B0000",
        "column": "Très petits (0-6 ans)",
        "short": "Très petits (0-6)"
    },
    "Petits (5-11 ans)": {
        "default": 10.0,
        "color": "#DC143C",
        "column": "Petits (5-11 ans)",
        "short": "Petits (5-11)"
    },
    "Moyens (10-15 ans)": {
        "default": 14.5,
        "color": "#FF4500",
        "column": "Moyens (10-15 ans)",
        "short": "Moyens (10-15)"
    },
    "Grands (14-18 ans)": {
        "default": 25.0,
        "color": "#FF6347",
        "column": "Grands (14-18 ans)",
        "short": "Grands (14-18)"
    },
    "Jeunes Adultes (17-21 ans)": {
        "default": 30.0,
        "color": "#FF69B4",
        "column": "Jeunes Adultes (17-21 ans)",
        "short": "Jeunes Ad. (17-21)"
    },
    "Adultes (sup 21 ans)": {
        "default": 30.0,
        "color": "#FDE0E0",
        "column": "Adultes (sup 21 ans)",
        "short": "Adultes (21+)"
    }
}

@st.cache_data
def load_default_data():
    """Load the categorized CSV file with caching"""
    try:
        df = pd.read_csv("Draft etablissements_categorized.csv", encoding='utf-8')
        df = df.dropna(subset=['lat', 'lng'])
        return df
    except Exception as e:
        st.error(f"Erreur de chargement du fichier par défaut: {e}")
        return pd.DataFrame(columns=['title', 'caracterisation', 'categorie', 'statut', 'lat', 'lng'] + age_group_priority)

# Category color mapping (main category -> base color, subcategory -> shade)
CATEGORY_COLORS = {
    # Formation - Blue shades
    "Formation : 1ier deg": "#1e90ff",       # dodger blue
    "Formation : College": "#4169e1",         # royal blue
    "Formation : Lycee pro": "#0000cd",       # medium blue
    "Formation : Lycee pro agricole": "#00008b",  # dark blue
    "Formation : Post-bac": "#191970",        # midnight blue
    
    # Protection de l'enfance - Red/Orange shades
    "Protection de l'enfance : MECs MNA": "#ff6347",      # tomato
    "Protection de l'enfance : MECs Fratrie": "#dc143c",  # crimson
    "Protection de l'enfance : MECs AEMO": "#b22222",     # firebrick
    "Protection de l'enfance : MECs Semi autnomie": "#8b0000",  # dark red
    
    # Insertion - Green shades
    "Insertion: Dispo insertion": "#32cd32",   # lime green
    "Inserttion : IAE": "#228b22",             # forest green
    
    # Parentalité - Purple shades
    "Parentialité : Maison des familles": "#9370db",  # medium purple
    "Parentalité : Creches": "#8a2be2",               # blue violet
    "Parentalité : Autres dispositifs parentalité": "#4b0082",  # indigo
}

# Main category colors for legend
MAIN_CATEGORY_COLORS = {
    "Formation": "#4169e1",              # Blue
    "Protection de l'enfance": "#dc143c", # Red
    "Insertion": "#32cd32",               # Green
    "Parentalité": "#9370db",             # Purple
}

def get_marker_color(categorie):
    """Get marker color based on category"""
    if pd.isna(categorie) or categorie == '':
        return "#808080"  # gray for unknown
    return CATEGORY_COLORS.get(categorie, "#808080")

def get_folium_icon_color(categorie):
    """Get Folium icon color based on main category"""
    main_cat = get_main_category(categorie)
    color_map = {
        "Formation": "blue",
        "Protection de l'enfance": "red",
        "Insertion": "green",
        "Parentalité": "purple",
        "Inconnu": "gray"
    }
    return color_map.get(main_cat, "gray")

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

# Track last API call time for rate limiting (20 req/min = 1 every 3 seconds)
if 'last_api_call' not in st.session_state:
    st.session_state.last_api_call = 0

# Load cache into session state and sync with disk
if 'isochrone_cache' not in st.session_state:
    st.session_state.isochrone_cache = load_isochrone_cache()
    add_log(f"📂 Disk→Memory: {len(st.session_state.isochrone_cache)} entries", "info")
else:
    # Session state exists - check if disk is behind and sync
    disk_cache = load_isochrone_cache()
    memory_count = len(st.session_state.isochrone_cache)
    disk_count = len(disk_cache)
    
    if memory_count > disk_count:
        # Memory has more - save to disk!
        if save_isochrone_cache(st.session_state.isochrone_cache):
            add_log(f"💾 Synced to disk: {memory_count} entries (was {disk_count})", "success")
        else:
            add_log(f"⚠️ Sync failed! Memory:{memory_count} Disk:{disk_count}", "error")
    elif disk_count > memory_count:
        # Disk has more (maybe updated externally) - reload
        st.session_state.isochrone_cache = disk_cache
        add_log(f"📂 Reloaded from disk: {disk_count} entries", "info")

def get_isochrone(lat, lng, time_seconds=600, profile='driving-car', max_retries=3):
    """Fetch isochrone (reachable area) from Mapbox API with memory caching"""
    # Create cache key (compatible with existing cache format)
    cache_key = f"{lat:.6f}_{lng:.6f}_{time_seconds}_{profile}"
    
    # Check if already cached in memory - NO disk read needed
    if cache_key in st.session_state.isochrone_cache:
        return st.session_state.isochrone_cache[cache_key]
    
    # Convert profile to Mapbox format
    mapbox_profile = "driving" if "car" in profile else "walking"
    
    # Convert seconds to minutes for Mapbox
    minutes = time_seconds // 60
    
    # Mapbox API URL
    url = f"https://api.mapbox.com/isochrone/v1/mapbox/{mapbox_profile}/{lng},{lat}"
    
    params = {
        "contours_minutes": minutes,
        "polygons": "true",
        "access_token": MAPBOX_TOKEN
    }
    
    for attempt in range(max_retries):
        try:
            st.session_state.last_api_call = time.time()
            response = requests.get(url, params=params, timeout=30)
            
            if response.status_code == 200:
                isochrone_data = response.json()
                
                # Extract polygon coordinates
                if isochrone_data and 'features' in isochrone_data and len(isochrone_data['features']) > 0:
                    result = isochrone_data['features'][0]['geometry']['coordinates']
                    # Save to memory cache
                    st.session_state.isochrone_cache[cache_key] = result
                    # Save to disk (persist) - immediately!
                    if save_isochrone_cache(st.session_state.isochrone_cache):
                        add_log(f"✓ Mapbox: {lat:.4f},{lng:.4f} (cache:{len(st.session_state.isochrone_cache)})", "success")
                    else:
                        add_log(f"✓ Mapbox OK but save failed: {lat:.4f},{lng:.4f}", "warning")
                    return result
                    
            elif response.status_code == 429:
                # Rate limited - short backoff (Mapbox is generous)
                wait_time = (2 ** attempt) * 2
                add_log(f"⏳ Rate limit, attente {wait_time}s (essai {attempt+1})", "warning")
                time.sleep(wait_time)
                continue
                
            else:
                add_log(f"✗ Erreur {response.status_code}: {lat:.4f},{lng:.4f}", "error")
                return None
                
        except requests.exceptions.Timeout:
            wait_time = (2 ** attempt) * 2
            add_log(f"⏳ Timeout, attente {wait_time}s (essai {attempt+1})", "warning")
            time.sleep(wait_time)
            continue
            
        except Exception as e:
            add_log(f"✗ Exception: {str(e)[:40]}", "error")
            return None
    
    add_log(f"✗ Échec: {lat:.4f},{lng:.4f}", "error")
    return None

# Initialize session state for data persistence
if 'df' not in st.session_state:
    st.session_state.df = load_default_data()

# ============================================
# SIDEBAR
# ============================================

with st.sidebar:
    # CSV Upload
    st.markdown("### 📤 Import")
    uploaded_file = st.file_uploader(
        "CSV",
        type=['csv'],
        help="Colonnes: title, lat, lng + 6 groupes d'âge",
        label_visibility="collapsed"
    )
    
    if uploaded_file is not None:
        try:
            uploaded_df = pd.read_csv(uploaded_file, encoding='utf-8')
            required_columns = ['title', 'lat', 'lng'] + [ag for ag in age_group_priority]
            missing = [c for c in required_columns if c not in uploaded_df.columns]
            
            if missing:
                st.error(f"❌ {len(missing)} colonnes manquantes")
            elif not pd.api.types.is_numeric_dtype(uploaded_df['lat']):
                st.error("❌ lat/lng invalides")
            else:
                st.success(f"✅ {len(uploaded_df)} lignes")
                if st.button("Remplacer", type="primary", use_container_width=True):
                    uploaded_df = uploaded_df.dropna(subset=['lat', 'lng'])
                    st.session_state.df = uploaded_df
                    st.rerun()
        except Exception as e:
            st.error(f"❌ {e}")
    
    # Reset to default button
    if st.button("🔄 Réinitialiser", use_container_width=True):
        st.cache_data.clear()
        st.session_state.df = load_default_data()
        st.rerun()
    
    st.markdown("---")

# Get current data from session state and filter to France hexagonale
df = st.session_state.df
# Filter to mainland France bounding box (drop overseas territories)
df = df[
    (df['lat'] >= 41) & (df['lat'] <= 52) &
    (df['lng'] >= -6) & (df['lng'] <= 10)
].copy()

# Isochrone durations configuration (Mapbox max: 60 min)
ISOCHRONE_DURATIONS_CAR = [
    (10, 600),    # 10 min = 600 seconds
    (15, 900),    # 15 min = 900 seconds
    (30, 1800),   # 30 min = 1800 seconds
    (40, 2400),   # 40 min = 2400 seconds
    (45, 2700),   # 45 min = 2700 seconds
    (60, 3600),   # 60 min = 3600 seconds
]

ISOCHRONE_DURATIONS_WALK = [
    (10, 600),    # 10 min = 600 seconds
    (15, 900),    # 15 min = 900 seconds
]

# Legend for marker colors - show subcategories with shades
with st.sidebar:
    st.markdown("### 🎨 Légende des établissements")
    
    # Group subcategories by main category
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
    
    if st.button("🗑️ Vider le cache", help="Supprime les zones en cache"):
        if os.path.exists(ISOCHRONE_CACHE_FILE):
            os.remove(ISOCHRONE_CACHE_FILE)
        st.session_state.isochrone_cache = {}
        st.session_state.api_logs = []
        st.success("Cache vidé!")
        st.rerun()
    
    st.markdown("---")

# Category statistics
with st.sidebar:
    st.markdown("### 📊 Par catégorie")
    
    if 'categorie' in df.columns:
        cat_counts = df['categorie'].apply(get_main_category).value_counts()
        for cat, count in cat_counts.items():
            color = MAIN_CATEGORY_COLORS.get(cat, "#808080")
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;padding:3px 0;">'
                f'<div style="width:12px;height:12px;background:{color};border-radius:50%;border:1px solid rgba(0,0,0,0.1);"></div>'
                f'<span style="font-size:0.8rem;color:#383838;">{cat}: <strong>{count}</strong></span>'
                f'</div>',
                unsafe_allow_html=True
            )
    
    st.caption(f"Total: {len(df)} établissements")
    st.markdown("---")


# ============================================
# MAP CREATION
# ============================================
center_lat = 46.7
center_lng = 2.5

m = folium.Map(
    location=[center_lat, center_lng],
    zoom_start=6,
    tiles=None
)

# OpenStreetMap standard tiles - clearer at all zoom levels
folium.TileLayer(
    tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    name='OpenStreetMap',
    max_zoom=19
).add_to(m)

# Helper function to check if EPCI is in mainland France
def is_mainland_epci(feature):
    """Check if EPCI centroid is in mainland France bounding box"""
    coords = feature.get('geometry', {}).get('coordinates', [])
    if not coords:
        return False
    try:
        geom_type = feature.get('geometry', {}).get('type')
        if geom_type == 'Polygon':
            lng, lat = coords[0][0][0], coords[0][0][1]
        elif geom_type == 'MultiPolygon':
            lng, lat = coords[0][0][0][0], coords[0][0][0][1]
        else:
            return True
        return -6 < lng < 10 and 41 < lat < 52
    except (IndexError, TypeError):
        return True

# Add QPV and EPCI layers (toggled via LayerControl on map, no page refresh)
qpv_data = load_qpv_geojson()
epci_with_counts = get_epci_qpv_counts()

# EPCI choropleth layer (only EPCIs with QPV > 0 AND in mainland France)
if epci_with_counts:
    filtered_epci = {
        'type': 'FeatureCollection',
        'features': [f for f in epci_with_counts['features'] 
                     if f['properties']['qpv_count'] > 0 and is_mainland_epci(f)]
    }
    
    if filtered_epci['features']:
        # Use quantile-based coloring to handle extreme values
        qpv_counts_list = sorted([f['properties']['qpv_count'] for f in filtered_epci['features']])
        n = len(qpv_counts_list)
        colors = ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d']
        
        # Calculate quantile breaks (7 colors = 7 bins)
        quantile_breaks = []
        for i in range(1, len(colors)):
            idx = int(n * i / len(colors))
            quantile_breaks.append(qpv_counts_list[min(idx, n-1)])
        
        def get_color_idx(qpv_count):
            for i, threshold in enumerate(quantile_breaks):
                if qpv_count <= threshold:
                    return i
            return len(colors) - 1
        
        def epci_style(feature):
            qpv_count = feature['properties'].get('qpv_count', 0)
            color_idx = get_color_idx(qpv_count)
            return {
                'fillColor': colors[color_idx],
                'color': '#666666',
                'weight': 0.5,
                'fillOpacity': 0.6
            }
        
        epci_layer = folium.FeatureGroup(name='EPCI par nb QPV', show=False)
        folium.GeoJson(
            filtered_epci,
            style_function=epci_style,
            highlight_function=lambda x: {
                'fillOpacity': 0.6,
                'weight': 3,
                'color': '#000000'
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'qpv_count'],
                aliases=['EPCI:', 'Nb QPV:'],
                sticky=False
            ),
            zoom_on_click=True
        ).add_to(epci_layer)
        epci_layer.add_to(m)

# QPV polygons layer (black/purple)
if qpv_data:
    qpv_layer = folium.FeatureGroup(name='QPV', show=False)
    folium.GeoJson(
        qpv_data,
        style_function=lambda x: {
            'fillColor': '#2d1b4e',
            'color': '#1a1a1a',
            'weight': 1,
            'fillOpacity': 0.4
        },
        highlight_function=lambda x: {
            'fillColor': '#4a3070',
            'fillOpacity': 0.4,
            'weight': 3,
            'color': '#000000'
        },
        tooltip=folium.GeoJsonTooltip(
            fields=['lib_qp', 'lib_com'],
            aliases=['QPV:', 'Commune:'],
            sticky=False
        ),
        zoom_on_click=True
    ).add_to(qpv_layer)
    qpv_layer.add_to(m)

# INSEE Indicator layer - Unemployment rate (F=female, H=male, T=total)
epci_with_indicators = get_epci_with_indicators()

if epci_with_indicators:
    # Filter to EPCIs with valid unemployment data AND in mainland France
    valid_features_chomage = [f for f in epci_with_indicators['features'] 
                              if f['properties'].get('chomage_T') is not None and is_mainland_epci(f)]
    
    # Debug info
    add_log(f"EPCIs with unemployment data: {len(valid_features_chomage)}")
    
    # Unemployment rate layer (blue gradient) - colored by T (total)
    if valid_features_chomage:
        chomage_values = [f['properties']['chomage_T'] for f in valid_features_chomage]
        
        # Quantile breaks for unemployment
        sorted_chomage = sorted(chomage_values)
        n = len(sorted_chomage)
        colors_blue = ['#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594']
        quantile_breaks_ch = [sorted_chomage[int(n * i / len(colors_blue))] for i in range(1, len(colors_blue))]
        
        def chomage_style(feature):
            val = feature['properties'].get('chomage_T')
            if val is None:
                return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
            idx = 0
            for i, threshold in enumerate(quantile_breaks_ch):
                if val <= threshold:
                    idx = i
                    break
                idx = i + 1
            idx = min(idx, len(colors_blue) - 1)
            return {'fillColor': colors_blue[idx], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
        
        chomage_layer = folium.FeatureGroup(name='Taux chômage (INSEE) 2022', show=False)
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': valid_features_chomage},
            style_function=chomage_style,
            highlight_function=lambda x: {'fillOpacity': 0.6, 'weight': 3, 'color': '#000000'},
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'chomage_T', 'chomage_F', 'chomage_H'],
                aliases=['EPCI:', 'Total (%):', 'Femmes (%):', 'Hommes (%):'],
                sticky=False
            ),
            zoom_on_click=True
        ).add_to(chomage_layer)
        chomage_layer.add_to(m)
    
    # Poverty rate layer (orange/red gradient) - matched by EPCI name
    valid_features_pauvrete = [f for f in epci_with_indicators['features'] 
                               if f['properties'].get('taux_pauvrete') is not None and is_mainland_epci(f)]
    
    add_log(f"EPCIs with poverty data: {len(valid_features_pauvrete)}")
    
    if valid_features_pauvrete:
        pauvrete_values = [f['properties']['taux_pauvrete'] for f in valid_features_pauvrete]
        
        # Quantile breaks for poverty
        sorted_pauv = sorted(pauvrete_values)
        n = len(sorted_pauv)
        colors_orange = ['#feedde', '#fdd0a2', '#fdae6b', '#fd8d3c', '#f16913', '#d94801', '#8c2d04']
        quantile_breaks_pv = [sorted_pauv[int(n * i / len(colors_orange))] for i in range(1, len(colors_orange))]
        
        def pauvrete_style(feature):
            val = feature['properties'].get('taux_pauvrete')
            if val is None:
                return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
            idx = 0
            for i, threshold in enumerate(quantile_breaks_pv):
                if val <= threshold:
                    idx = i
                    break
                idx = i + 1
            idx = min(idx, len(colors_orange) - 1)
            return {'fillColor': colors_orange[idx], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
        
        pauvrete_layer = folium.FeatureGroup(name='Taux pauvreté (INSEE) 2022', show=False)
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': valid_features_pauvrete},
            style_function=pauvrete_style,
            highlight_function=lambda x: {'fillOpacity': 0.6, 'weight': 3, 'color': '#000000'},
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'taux_pauvrete'],
                aliases=['EPCI:', 'Taux pauvreté (%):'],
                sticky=False
            ),
            zoom_on_click=True
        ).add_to(pauvrete_layer)
        pauvrete_layer.add_to(m)
    
    # NEETs rate layer (15-24 not in education/employment) - purple gradient
    valid_features_neets = [f for f in epci_with_indicators['features'] 
                            if f['properties'].get('neets') is not None and is_mainland_epci(f)]
    
    add_log(f"EPCIs with NEETs data: {len(valid_features_neets)}")
    
    if valid_features_neets:
        neets_values = [f['properties']['neets'] for f in valid_features_neets]
        
        # Quantile breaks for NEETs
        sorted_neets = sorted(neets_values)
        n = len(sorted_neets)
        colors_purple = ['#f2f0f7', '#dadaeb', '#bcbddc', '#9e9ac8', '#807dba', '#6a51a3', '#4a1486']
        quantile_breaks_neets = [sorted_neets[int(n * i / len(colors_purple))] for i in range(1, len(colors_purple))]
        
        def neets_style(feature):
            val = feature['properties'].get('neets')
            if val is None:
                return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
            idx = 0
            for i, threshold in enumerate(quantile_breaks_neets):
                if val <= threshold:
                    idx = i
                    break
                idx = i + 1
            idx = min(idx, len(colors_purple) - 1)
            return {'fillColor': colors_purple[idx], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
        
        neets_layer = folium.FeatureGroup(name='Part NEETs 15-24 (INSEE) 2022', show=False)
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': valid_features_neets},
            style_function=neets_style,
            highlight_function=lambda x: {'fillOpacity': 0.6, 'weight': 3, 'color': '#000000'},
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'neets'],
                aliases=['EPCI:', 'NEETs 15-24 (%):'],
                sticky=False
            ),
            zoom_on_click=True
        ).add_to(neets_layer)
        neets_layer.add_to(m)
    
    # Sans diplôme layer (15+ without diploma) - green gradient
    valid_features_diplome = [f for f in epci_with_indicators['features'] 
                              if f['properties'].get('sans_diplome_T') is not None and is_mainland_epci(f)]
    
    add_log(f"EPCIs with sans diplôme data: {len(valid_features_diplome)}")
    
    if valid_features_diplome:
        diplome_values = [f['properties']['sans_diplome_T'] for f in valid_features_diplome]
        
        # Quantile breaks for sans diplôme
        sorted_diplome = sorted(diplome_values)
        n = len(sorted_diplome)
        colors_green = ['#edf8e9', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#005a32']
        quantile_breaks_diplome = [sorted_diplome[int(n * i / len(colors_green))] for i in range(1, len(colors_green))]
        
        def diplome_style(feature):
            val = feature['properties'].get('sans_diplome_T')
            if val is None:
                return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
            idx = 0
            for i, threshold in enumerate(quantile_breaks_diplome):
                if val <= threshold:
                    idx = i
                    break
                idx = i + 1
            idx = min(idx, len(colors_green) - 1)
            return {'fillColor': colors_green[idx], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
        
        diplome_layer = folium.FeatureGroup(name='Part +15 ans sans diplôme (INSEE) 2022', show=False)
        folium.GeoJson(
            {'type': 'FeatureCollection', 'features': valid_features_diplome},
            style_function=diplome_style,
            highlight_function=lambda x: {'fillOpacity': 0.6, 'weight': 3, 'color': '#000000'},
            tooltip=folium.GeoJsonTooltip(
                fields=['libgeo', 'sans_diplome_T', 'sans_diplome_F', 'sans_diplome_H'],
                aliases=['EPCI:', 'Total (%):', 'Femmes (%):', 'Hommes (%):'],
                sticky=False
            ),
            zoom_on_click=True
        ).add_to(diplome_layer)
        diplome_layer.add_to(m)

# Load cached isochrones (no API calls, just from cache)
locations_df = df[['title', 'lat', 'lng']].copy()
locations_df['lat_key'] = locations_df['lat'].round(6)
locations_df['lng_key'] = locations_df['lng'].round(6)
unique_locations = locations_df.groupby(['lat_key', 'lng_key'], as_index=False).agg(
    titles=('title', lambda x: list(x))
)

# Color palette for different durations
duration_colors_car = {
    600: '#a6cee3',   # 10 min - light blue
    900: '#6baed6',   # 15 min - blue
    1800: '#1f78b4',  # 30 min - medium blue
    2400: '#b2df8a',  # 40 min - light green
    2700: '#33a02c',  # 45 min - medium green
    3600: '#fb9a99',  # 60 min - light red
}

duration_colors_walk = {
    600: '#a1d99b',   # 10 min - light green
    900: '#31a354',   # 15 min - green
}

# Build ALL isochrone layers from cache (driving) - pre-loaded, toggleable
for minutes, seconds in ISOCHRONE_DURATIONS_CAR:
    features = []
    fill_color = duration_colors_car.get(seconds, '#4a90d9')
    
    for _, row in unique_locations.iterrows():
        lat = row['lat_key']
        lng = row['lng_key']
        titles = row['titles']
        cache_key = f"{lat:.6f}_{lng:.6f}_{seconds}_driving-car"
        
        if cache_key in st.session_state.isochrone_cache:
            isochrone_coords = st.session_state.isochrone_cache[cache_key]
            
            if isochrone_coords and len(isochrone_coords) > 0:
                names_html = "<br>".join(titles)
                label = titles[0]
                if len(titles) > 1:
                    label = f"{titles[0]} (+{len(titles)-1})"
                
                features.append({
                    "type": "Feature",
                    "properties": {
                        "name": label,
                        "count": len(titles),
                        "names": names_html
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": isochrone_coords
                    }
                })
    
    if features:
        geojson_data = {"type": "FeatureCollection", "features": features}
        isochrone_layer = folium.FeatureGroup(name=f"🚗 {minutes} min", show=False)
        folium.GeoJson(
            geojson_data,
            style_function=lambda x, fc=fill_color: {
                'fillColor': fc,
                'color': '#333333',
                'weight': 1,
                'fillOpacity': 0.25
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['names'],
                aliases=[''],
                labels=False,
                sticky=True,
                parse_html=True
            )
        ).add_to(isochrone_layer)
        isochrone_layer.add_to(m)

# Build ALL isochrone layers from cache (walking) - pre-loaded, toggleable
for minutes, seconds in ISOCHRONE_DURATIONS_WALK:
    features_walk = []
    fill_color = duration_colors_walk.get(seconds, '#5cb85c')
    
    for _, row in unique_locations.iterrows():
        lat = row['lat_key']
        lng = row['lng_key']
        titles = row['titles']
        cache_key = f"{lat:.6f}_{lng:.6f}_{seconds}_foot-walking"
        
        if cache_key in st.session_state.isochrone_cache:
            isochrone_coords = st.session_state.isochrone_cache[cache_key]
            
            if isochrone_coords and len(isochrone_coords) > 0:
                names_html = "<br>".join(titles)
                label = titles[0]
                if len(titles) > 1:
                    label = f"{titles[0]} (+{len(titles)-1})"
                
                features_walk.append({
                    "type": "Feature",
                    "properties": {
                        "name": label,
                        "count": len(titles),
                        "names": names_html
                    },
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": isochrone_coords
                    }
                })
    
    if features_walk:
        geojson_data = {"type": "FeatureCollection", "features": features_walk}
        walk_layer = folium.FeatureGroup(name=f"🚶 {minutes} min", show=False)
        folium.GeoJson(
            geojson_data,
            style_function=lambda x, fc=fill_color: {
                'fillColor': fc,
                'color': '#333333',
                'weight': 1,
                'fillOpacity': 0.25
            },
            tooltip=folium.GeoJsonTooltip(
                fields=['names'],
                aliases=[''],
                labels=False,
                sticky=True,
                parse_html=True
            )
        ).add_to(walk_layer)
        walk_layer.add_to(m)

# Markers in a FeatureGroup
markers_layer = folium.FeatureGroup(name='Établissements', show=True)
for idx, row in df.iterrows():
    title = row['title']
    lat = row['lat']
    lng = row['lng']
    
    served = [ag for ag in age_group_priority 
              if str(row.get(age_groups[ag]["column"], '')).upper() == 'TRUE']
    
    # Get category info
    categorie = row.get('categorie', '') if 'categorie' in row.index else ''
    caracterisation = row.get('caracterisation', '') if 'caracterisation' in row.index else ''
    main_cat = get_main_category(categorie)
    marker_color = get_marker_color(categorie)
    
    # Build popup with category info
    popup = f"""
    <div style="font-family: Inter, sans-serif; min-width: 220px;">
        <div style="font-weight: 600; font-size: 13px; color: #383838; margin-bottom: 4px;">{title}</div>
        <div style="background:{marker_color};color:white;padding:3px 8px;border-radius:4px;font-size:10px;margin-bottom:6px;display:inline-block;">{main_cat}</div>
        <div style="font-size:10px;color:#666;margin-bottom:6px;">{categorie}</div>
        <div style="display: flex; flex-wrap: wrap; gap: 3px;">
    """
    
    for ag in served:
        c = age_groups[ag]["color"]
        popup += f'<span style="background:{c};color:white;padding:2px 6px;border-radius:3px;font-size:9px;">{age_groups[ag]["short"]}</span>'
    
    popup += "</div></div>"
    
    # Create pin marker with subcategory shade color using DivIcon
    # This allows custom hex colors for each subcategory
    pin_html = f'''
    <div style="position:relative;">
        <svg width="25" height="41" viewBox="0 0 25 41" xmlns="http://www.w3.org/2000/svg">
            <path fill="{marker_color}" stroke="#333" stroke-width="1" d="M12.5 0C5.6 0 0 5.6 0 12.5c0 2.4.7 4.7 1.9 6.6L12.5 41l10.6-21.9c1.2-1.9 1.9-4.2 1.9-6.6C25 5.6 19.4 0 12.5 0z"/>
            <circle fill="white" cx="12.5" cy="12.5" r="5"/>
        </svg>
    </div>
    '''
    icon = folium.DivIcon(
        html=pin_html,
        icon_size=(25, 41),
        icon_anchor=(12, 41),
        popup_anchor=(0, -35)
    )
    
    # Tooltip with category
    tooltip_text = f"{title} | {main_cat}"
    
    folium.Marker(
        location=[lat, lng],
        popup=folium.Popup(popup, max_width=300),
        tooltip=tooltip_text,
        icon=icon
    ).add_to(markers_layer)

markers_layer.add_to(m)

# Add layer control with all layers - isochrones will be toggleable
folium.LayerControl(collapsed=False, position='topright').add_to(m)

# ============================================
# MAIN CONTENT
# ============================================

# Map (full width) - cache the HTML and serve it directly for instant loading
# The LayerControl is pure JavaScript, so interactions don't need Python
map_html = m._repr_html_()

# Display the cached map HTML - no Python processing needed for interactions
st.markdown('<div class="map-container">', unsafe_allow_html=True)
components.html(map_html, height=700, scrolling=False)
st.markdown('</div>', unsafe_allow_html=True)

# Data section
st.markdown("---")

with st.expander("📋 Gérer les données", expanded=False):
    st.markdown("Double-cliquez pour modifier. Utilisez '+' pour ajouter.")
    
    edited_df = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "title": st.column_config.TextColumn("Établissement", required=True),
            "categorie": st.column_config.TextColumn("Catégorie", width="medium"),
            "caracterisation": st.column_config.TextColumn("Description", width="large"),
            "statut": st.column_config.TextColumn("Statut", width="small"),
            "lat": st.column_config.NumberColumn("Lat", required=True, format="%.4f"),
            "lng": st.column_config.NumberColumn("Lng", required=True, format="%.4f"),
            "capacity": st.column_config.TextColumn("Cap."),
            **{ag: st.column_config.CheckboxColumn(age_groups[ag]["short"]) for ag in age_group_priority}
        }
    )
    
    if not edited_df.equals(df):
        c1, c2, c3 = st.columns([3, 1, 1])
        with c2:
            if st.button("💾 Appliquer", type="primary", use_container_width=True):
                st.session_state.df = edited_df
                st.rerun()
        with c3:
            if st.button("❌ Annuler", use_container_width=True):
                st.rerun()
    
    # Download button for current data
    st.markdown("---")
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False, encoding='utf-8')
    st.download_button(
        label="📥 Télécharger les données (CSV)",
        data=csv_buffer.getvalue(),
        file_name="etablissements_export.csv",
        mime="text/csv",
        use_container_width=True
    )

with st.expander("❓ Aide", expanded=False):
    st.markdown("""
    **Navigation** · Molette = zoom · Glisser = déplacer · Clic marqueur = détails
    
    **Marqueurs par catégorie:**
    - 🔵 Bleu = Formation
    - 🔴 Rouge = Protection de l'enfance
    - 🟢 Vert = Insertion
    - 🟣 Violet = Parentalité
    
    **Zones d'accès** · Cochez 🚗 ou 🚶 dans le panneau de couches (en haut à droite de la carte)
    
    **Autres couches** · QPV, EPCI, indicateurs INSEE également disponibles dans le panneau
    
    **Données** · Téléchargez vos modifications avant de quitter.
    """)

