import streamlit as st

# Page config must be first
st.set_page_config(
    page_title="Outil de dataviz - Apprentis d'Auteuil",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

import pandas as pd
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Category colors for legend
CATEGORY_COLORS = {
    "Formation : 1ier deg": "#74b9ff",
    "Formation : College": "#0984e3",
    "Formation : Lycee pro": "#0652DD",
    "Formation : Lycee pro agricole": "#1B1464",
    "Formation : Post-bac": "#0c2461",
    "Protection de l'enfance : MECs MNA": "#ff7675",
    "Protection de l'enfance : MECs Fratrie": "#d63031",
    "Protection de l'enfance : MECs AEMO": "#b71540",
    "Protection de l'enfance : MECs Semi autnomie": "#6F1E51",
    "Insertion: Dispo insertion": "#a29bfe",
    "Inserttion : IAE": "#6c5ce7",
    "Parentialité : Maison des familles": "#55efc4",
    "Parentalité : Creches": "#00b894",
    "Parentalité : Autres dispositifs parentalité": "#006266",
}

MAIN_CATEGORY_COLORS = {
    "Formation": "#0984e3",
    "Protection de l'enfance": "#d63031",
    "Insertion": "#6c5ce7",
    "Parentalité": "#00b894",
    "Autre": "#636e72"
}

def get_main_category(categorie):
    if not categorie:
        return "Autre"
    cat_lower = str(categorie).lower()
    if 'formation' in cat_lower:
        return "Formation"
    elif 'protection' in cat_lower:
        return "Protection de l'enfance"
    elif 'insertion' in cat_lower:
        return "Insertion"
    elif 'parent' in cat_lower:
        return "Parentalité"
    return "Autre"

# Custom CSS
st.markdown("""
<style>
    /* Apprentis d'Auteuil branding */
    .stApp > header {background-color: #c8102e !important;}
    section[data-testid="stSidebar"] {background-color: #f8f9fa; border-right: 1px solid #e9ecef;}
    section[data-testid="stSidebar"] > div:first-child {padding-top: 1rem;}
    
    /* Title bar */
    .main-title {
        background: linear-gradient(135deg, #c8102e 0%, #a00d24 100%);
        color: white;
        padding: 1rem 1.5rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        font-family: 'Inter', sans-serif;
    }
    .main-title h1 {
        margin: 0;
        font-size: 1.5rem;
        font-weight: 600;
    }
    
    /* Map container */
    .map-frame {
        border: none;
        border-radius: 8px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
    }
</style>
""", unsafe_allow_html=True)

# Title
st.markdown("""
<div class="main-title">
    <h1>🏠 Outil de dataviz pour les Apprentis d'Auteuil</h1>
</div>
""", unsafe_allow_html=True)

# Load establishments data for sidebar stats
@st.cache_data
def load_data():
    csv_path = os.path.join(SCRIPT_DIR, "Draft etablissements_categorized.csv")
    df = pd.read_csv(csv_path, encoding='utf-8')
    df = df[(df['lat'] >= 41) & (df['lat'] <= 52) & (df['lng'] >= -6) & (df['lng'] <= 10)]
    return df

df = load_data()

# Sidebar
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
                f'<div style="width:12px;height:12px;background:{color};border-radius:50%;border:1px solid rgba(0,0,0,0.1);"></div>'
                f'<span style="font-size:0.8rem;color:#383838;">{cat}: <strong>{count}</strong></span>'
                f'</div>',
                unsafe_allow_html=True
            )
    
    st.caption(f"Total: {len(df)} établissements")
    
    st.markdown("---")
    st.markdown("### ℹ️ Utilisation")
    st.markdown("""
    - Utilisez les **contrôles** en haut à droite de la carte pour activer/désactiver les couches
    - **Cliquez** sur un marqueur pour voir les détails
    - **Survolez** une zone pour voir les statistiques
    """)

# Load and display the static map
@st.cache_data
def load_map_html():
    map_path = os.path.join(SCRIPT_DIR, "map.html")
    with open(map_path, 'r', encoding='utf-8') as f:
        return f.read()

map_html = load_map_html()

# Display map using iframe with data URL to prevent reloading
import base64
map_b64 = base64.b64encode(map_html.encode()).decode()

st.markdown(
    f'<iframe src="data:text/html;base64,{map_b64}" '
    f'width="100%" height="700" class="map-frame" '
    f'style="border:none;border-radius:8px;"></iframe>',
    unsafe_allow_html=True
)

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align:center;color:#666;font-size:0.8rem;">
    Données: INSEE 2022 | QPV: ANCT 2024 | EPCI: data.gouv.fr 2025
</div>
""", unsafe_allow_html=True)
