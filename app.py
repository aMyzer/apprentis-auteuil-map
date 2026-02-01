import streamlit as st

st.set_page_config(page_title="Apprentis d'Auteuil", page_icon="🏠", layout="wide")

import streamlit.components.v1 as components
import folium
import pandas as pd
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Colors
COLORS = {
    "Formation": "#4169e1",
    "Protection": "#dc143c", 
    "Insertion": "#32cd32",
    "Parentalité": "#9370db",
}

def get_category(cat):
    if pd.isna(cat): return "Autre"
    cat = str(cat)
    if "Formation" in cat: return "Formation"
    if "Protection" in cat: return "Protection"
    if "Insertion" in cat: return "Insertion"
    if "Parent" in cat: return "Parentalité"
    return "Autre"

@st.cache_resource
def load_data():
    df = pd.read_csv(os.path.join(SCRIPT_DIR, "Draft etablissements_categorized.csv"))
    df = df.dropna(subset=['lat', 'lng'])
    df = df[(df['lat'] >= 41) & (df['lat'] <= 52) & (df['lng'] >= -6) & (df['lng'] <= 10)]
    return df

@st.cache_resource  
def build_map():
    df = load_data()
    
    m = folium.Map(location=[46.7, 2.5], zoom_start=6)
    
    for _, row in df.iterrows():
        cat = get_category(row.get('categorie', ''))
        color = COLORS.get(cat, '#808080')
        
        folium.CircleMarker(
            location=[row['lat'], row['lng']],
            radius=7,
            color='#333',
            weight=1,
            fill=True,
            fillColor=color,
            fillOpacity=0.8,
            popup=str(row.get('title', '')),
            tooltip=str(row.get('title', ''))
        ).add_to(m)
    
    return m._repr_html_()

# UI
st.markdown('<div style="background:#C8102E;color:white;padding:1rem;border-radius:8px;margin-bottom:1rem;"><b>🏠 Carte des Apprentis d\'Auteuil</b></div>', unsafe_allow_html=True)

df = load_data()

with st.sidebar:
    st.markdown("### Statistiques")
    st.write(f"**Total:** {len(df)}")
    for cat, color in COLORS.items():
        count = len(df[df['categorie'].apply(get_category) == cat])
        st.markdown(f'<span style="color:{color}">●</span> {cat}: {count}', unsafe_allow_html=True)

html = build_map()
components.html(html, height=650)
