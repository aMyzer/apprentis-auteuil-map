"""
Generate static map.html file for Streamlit deployment.
Run this script locally whenever you need to update the map.

Usage: python generate_map.py
"""

import folium
import pandas as pd
import json
import os
import unicodedata
import copy

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def normalize_name(name):
    """Normalize EPCI name for matching (remove accents, lowercase, strip)"""
    if not isinstance(name, str):
        return ''
    nfkd = unicodedata.normalize('NFKD', name)
    ascii_name = ''.join(c for c in nfkd if not unicodedata.combining(c))
    return ascii_name.lower().strip()

def is_france_hexagonale(dept_code):
    """Check if department is in mainland France (not overseas)"""
    if not dept_code:
        return False
    return len(dept_code) <= 2 or dept_code.startswith('2')

def simplify_coords(coords, precision=3):
    """Reduce coordinate precision for smaller file size"""
    if isinstance(coords[0], (int, float)):
        return [round(c, precision) for c in coords]
    return [simplify_coords(c, precision) for c in coords]

def load_qpv_geojson():
    """Load QPV geojson - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "QP2024_France_Hexagonale_Outre_Mer_WGS84.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        data['features'] = [
            f for f in data['features'] 
            if is_france_hexagonale(f.get('properties', {}).get('insee_dep'))
        ]
        for feature in data['features']:
            if 'geometry' in feature and 'coordinates' in feature['geometry']:
                feature['geometry']['coordinates'] = simplify_coords(feature['geometry']['coordinates'])
        return data
    return None

def load_epci_geojson():
    """Load EPCI boundaries geojson - France hexagonale only"""
    geojson_path = os.path.join(SCRIPT_DIR, "epci_2025_complete.geojson")
    if os.path.exists(geojson_path):
        with open(geojson_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        overseas_keywords = ['Guadeloupe', 'Martinique', 'Guyane', 'Mayotte', 'Réunion', 
                            'Reunion', 'Levant', 'Saint-Martin', 'Saint-Pierre',
                            'Basse-Terre', 'Caraïbe', 'Caraibe', 'Cap Excellence',
                            'Grande-Terre', 'Marie-Galante', 'Savanes', 'Dembeni', 'Petite-Terre',
                            'Centre Ouest', 'Nord Grande']
        overseas_exact_names = ['CC du Sud', 'CC du Centre Ouest', 'CC du Centre-Ouest']
        overseas_code_prefixes = ['24971', '24972', '24973', '24974', '24976', '249720', '249730', '249740']
        
        def is_overseas_name(name):
            if not name:
                return False
            if name in overseas_exact_names:
                return True
            name_lower = name.lower()
            return any(kw.lower() in name_lower for kw in overseas_keywords)
        
        def is_overseas_code(code):
            if not code:
                return False
            return any(code.startswith(prefix) for prefix in overseas_code_prefixes)
        
        def in_mainland(feature):
            props = feature.get('properties', {})
            name = props.get('libgeo', '')
            if is_overseas_name(name):
                return False
            code = props.get('codgeo', '')
            if is_overseas_code(code):
                return False
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
        
        data['features'] = [f for f in data['features'] if in_mainland(f)]
        for feature in data['features']:
            if 'geometry' in feature and 'coordinates' in feature['geometry']:
                feature['geometry']['coordinates'] = simplify_coords(feature['geometry']['coordinates'])
        return data
    return None

def load_indicator_csvs():
    """Load all INSEE indicator CSVs"""
    epci_data = load_epci_geojson()
    if not epci_data:
        return None
    
    valid_codes = set(f['properties']['codgeo'] for f in epci_data['features'])
    valid_names = set(normalize_name(f['properties']['libgeo']) for f in epci_data['features'])
    
    # Load unemployment
    chomage_data = {}
    chomage_path = os.path.join(SCRIPT_DIR, "taux_chomage_epci.csv")
    if os.path.exists(chomage_path):
        df = pd.read_csv(chomage_path)
        df['codgeo'] = df['codgeo'].astype(str)
        df = df[df['codgeo'].isin(valid_codes)]
        pivot = df.pivot(index='codgeo', columns='sexe', values='tx_chom1564').reset_index()
        pivot.columns = ['codgeo', 'chomage_F', 'chomage_H', 'chomage_T']
        names = df[['codgeo', 'libgeo']].drop_duplicates()
        pivot = pivot.merge(names, on='codgeo', how='left')
        chomage_data = pivot.set_index('codgeo').to_dict('index')
    
    # Load poverty
    pauvrete_data = {}
    pauvrete_path = os.path.join(SCRIPT_DIR, "taux_pauvrete_epci.csv")
    if os.path.exists(pauvrete_path):
        df = pd.read_csv(pauvrete_path)
        df.columns = ['libgeo', 'taux_pauvrete']
        df['libgeo_normalized'] = df['libgeo'].apply(normalize_name)
        df = df[df['libgeo_normalized'].isin(valid_names)]
        df = df.drop_duplicates(subset='libgeo_normalized', keep='first')
        pauvrete_data = df.set_index('libgeo_normalized').to_dict('index')
    
    # Load NEETs
    neets_data = {}
    neets_path = os.path.join(SCRIPT_DIR, "15-24_neets_epci.csv")
    if os.path.exists(neets_path):
        df = pd.read_csv(neets_path)
        df['codgeo'] = df['codgeo'].astype(str)
        df = df[df['codgeo'].isin(valid_codes)]
        neets_data = df.set_index('codgeo').to_dict('index')
    
    # Load sans diplome
    sans_diplome_data = {}
    diplome_path = os.path.join(SCRIPT_DIR, "15+_sans_diplomes_epci.csv")
    if os.path.exists(diplome_path):
        df = pd.read_csv(diplome_path)
        df['codgeo'] = df['codgeo'].astype(str)
        df = df[df['codgeo'].isin(valid_codes)]
        pivot = df.pivot(index='codgeo', columns='sexe', values='p_nondipl15').reset_index()
        pivot.columns = ['codgeo', 'sans_diplome_F', 'sans_diplome_H', 'sans_diplome_T']
        names = df[['codgeo', 'libgeo']].drop_duplicates()
        pivot = pivot.merge(names, on='codgeo', how='left')
        sans_diplome_data = pivot.set_index('codgeo').to_dict('index')
    
    return chomage_data, pauvrete_data, neets_data, sans_diplome_data

def load_isochrone_cache():
    """Load isochrone cache from file"""
    cache_path = os.path.join(SCRIPT_DIR, "isochrone_cache.json")
    if os.path.exists(cache_path):
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def get_main_category(categorie):
    """Get main category from full category string"""
    if not categorie:
        return "Autre"
    cat_lower = categorie.lower()
    if 'formation' in cat_lower:
        return "Formation"
    elif 'protection' in cat_lower:
        return "Protection de l'enfance"
    elif 'insertion' in cat_lower:
        return "Insertion"
    elif 'parent' in cat_lower:
        return "Parentalité"
    return "Autre"

# Category colors
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

def get_marker_color(categorie):
    """Get marker color for a category"""
    if categorie in CATEGORY_COLORS:
        return CATEGORY_COLORS[categorie]
    main_cat = get_main_category(categorie)
    return MAIN_CATEGORY_COLORS.get(main_cat, "#636e72")

def generate_map():
    """Generate the complete map and save as HTML"""
    print("Loading data...")
    
    # Load all data
    qpv_data = load_qpv_geojson()
    epci_data = load_epci_geojson()
    chomage_data, pauvrete_data, neets_data, sans_diplome_data = load_indicator_csvs()
    isochrone_cache = load_isochrone_cache()
    
    # Load establishments
    csv_path = os.path.join(SCRIPT_DIR, "Draft etablissements_categorized.csv")
    df = pd.read_csv(csv_path, encoding='utf-8')
    df = df[(df['lat'] >= 41) & (df['lat'] <= 52) & (df['lng'] >= -6) & (df['lng'] <= 10)].copy()
    
    print(f"Loaded {len(df)} establishments")
    print(f"QPV features: {len(qpv_data['features']) if qpv_data else 0}")
    print(f"EPCI features: {len(epci_data['features']) if epci_data else 0}")
    print(f"Isochrone cache entries: {len(isochrone_cache)}")
    
    # Create map
    print("Creating map...")
    m = folium.Map(location=[46.7, 2.5], zoom_start=6, tiles=None)
    
    # Add OpenStreetMap tiles
    folium.TileLayer(
        tiles='https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        attr='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        name='OpenStreetMap',
        max_zoom=19
    ).add_to(m)
    
    def is_mainland_epci(feature):
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
    
    # Enrich EPCI with indicators
    if epci_data:
        epci_enriched = copy.deepcopy(epci_data)
        qpv_counts = {}
        if qpv_data:
            for feature in qpv_data.get('features', []):
                siren_epci = feature.get('properties', {}).get('siren_epci')
                if siren_epci:
                    qpv_counts[siren_epci] = qpv_counts.get(siren_epci, 0) + 1
        
        for feature in epci_enriched.get('features', []):
            codgeo = feature.get('properties', {}).get('codgeo')
            libgeo = feature.get('properties', {}).get('libgeo')
            libgeo_norm = normalize_name(libgeo)
            feature['properties']['qpv_count'] = qpv_counts.get(codgeo, 0)
            if codgeo in chomage_data:
                ch = chomage_data[codgeo]
                feature['properties']['chomage_F'] = ch.get('chomage_F')
                feature['properties']['chomage_H'] = ch.get('chomage_H')
                feature['properties']['chomage_T'] = ch.get('chomage_T')
            if libgeo_norm in pauvrete_data:
                feature['properties']['taux_pauvrete'] = pauvrete_data[libgeo_norm].get('taux_pauvrete')
            if codgeo in neets_data:
                feature['properties']['neets'] = neets_data[codgeo].get('part_non_inseres')
            if codgeo in sans_diplome_data:
                sd = sans_diplome_data[codgeo]
                feature['properties']['sans_diplome_F'] = sd.get('sans_diplome_F')
                feature['properties']['sans_diplome_H'] = sd.get('sans_diplome_H')
                feature['properties']['sans_diplome_T'] = sd.get('sans_diplome_T')
    
    # Add EPCI layer (by QPV count)
    print("Adding EPCI layer...")
    if epci_enriched:
        filtered_epci = {
            'type': 'FeatureCollection',
            'features': [f for f in epci_enriched['features'] 
                         if f['properties']['qpv_count'] > 0 and is_mainland_epci(f)]
        }
        
        if filtered_epci['features']:
            qpv_counts_list = sorted([f['properties']['qpv_count'] for f in filtered_epci['features']])
            n = len(qpv_counts_list)
            colors = ['#fee5d9', '#fcbba1', '#fc9272', '#fb6a4a', '#ef3b2c', '#cb181d', '#99000d']
            quantile_breaks = [qpv_counts_list[int(n * i / len(colors))] for i in range(1, len(colors))]
            
            def get_color_idx(qpv_count):
                for i, threshold in enumerate(quantile_breaks):
                    if qpv_count <= threshold:
                        return i
                return len(colors) - 1
            
            def epci_style(feature):
                qpv_count = feature['properties'].get('qpv_count', 0)
                color_idx = get_color_idx(qpv_count)
                return {'fillColor': colors[color_idx], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
            
            epci_layer = folium.FeatureGroup(name='EPCI par nb QPV', show=False)
            folium.GeoJson(
                filtered_epci,
                style_function=epci_style,
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'qpv_count'], aliases=['EPCI:', 'Nb QPV:'])
            ).add_to(epci_layer)
            epci_layer.add_to(m)
    
    # Add QPV layer
    print("Adding QPV layer...")
    if qpv_data:
        qpv_layer = folium.FeatureGroup(name='QPV', show=False)
        folium.GeoJson(
            qpv_data,
            style_function=lambda x: {'fillColor': '#2d1b4e', 'color': '#1a1a1a', 'weight': 1, 'fillOpacity': 0.4},
            tooltip=folium.GeoJsonTooltip(fields=['lib_qp', 'lib_com'], aliases=['QPV:', 'Commune:'])
        ).add_to(qpv_layer)
        qpv_layer.add_to(m)
    
    # Add indicator layers
    print("Adding indicator layers...")
    if epci_enriched:
        # Unemployment layer
        valid_chomage = [f for f in epci_enriched['features'] if f['properties'].get('chomage_T') is not None and is_mainland_epci(f)]
        if valid_chomage:
            sorted_vals = sorted([f['properties']['chomage_T'] for f in valid_chomage])
            n = len(sorted_vals)
            colors_blue = ['#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#4292c6', '#2171b5', '#084594']
            breaks = [sorted_vals[int(n * i / len(colors_blue))] for i in range(1, len(colors_blue))]
            
            def chomage_style(feature):
                val = feature['properties'].get('chomage_T')
                if val is None:
                    return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
                idx = next((i for i, t in enumerate(breaks) if val <= t), len(colors_blue) - 1)
                return {'fillColor': colors_blue[min(idx, len(colors_blue)-1)], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
            
            chomage_layer = folium.FeatureGroup(name='Taux chômage (INSEE) 2022', show=False)
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': valid_chomage},
                style_function=chomage_style,
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'chomage_T'], aliases=['EPCI:', 'Chômage (%):'])
            ).add_to(chomage_layer)
            chomage_layer.add_to(m)
        
        # Poverty layer
        valid_pauv = [f for f in epci_enriched['features'] if f['properties'].get('taux_pauvrete') is not None and is_mainland_epci(f)]
        if valid_pauv:
            sorted_vals = sorted([f['properties']['taux_pauvrete'] for f in valid_pauv])
            n = len(sorted_vals)
            colors_orange = ['#feedde', '#fdd0a2', '#fdae6b', '#fd8d3c', '#f16913', '#d94801', '#8c2d04']
            breaks = [sorted_vals[int(n * i / len(colors_orange))] for i in range(1, len(colors_orange))]
            
            def pauv_style(feature):
                val = feature['properties'].get('taux_pauvrete')
                if val is None:
                    return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
                idx = next((i for i, t in enumerate(breaks) if val <= t), len(colors_orange) - 1)
                return {'fillColor': colors_orange[min(idx, len(colors_orange)-1)], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
            
            pauv_layer = folium.FeatureGroup(name='Taux pauvreté (INSEE) 2022', show=False)
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': valid_pauv},
                style_function=pauv_style,
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'taux_pauvrete'], aliases=['EPCI:', 'Pauvreté (%):'])
            ).add_to(pauv_layer)
            pauv_layer.add_to(m)
        
        # NEETs layer
        valid_neets = [f for f in epci_enriched['features'] if f['properties'].get('neets') is not None and is_mainland_epci(f)]
        if valid_neets:
            sorted_vals = sorted([f['properties']['neets'] for f in valid_neets])
            n = len(sorted_vals)
            colors_purple = ['#f2f0f7', '#dadaeb', '#bcbddc', '#9e9ac8', '#807dba', '#6a51a3', '#4a1486']
            breaks = [sorted_vals[int(n * i / len(colors_purple))] for i in range(1, len(colors_purple))]
            
            def neets_style(feature):
                val = feature['properties'].get('neets')
                if val is None:
                    return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
                idx = next((i for i, t in enumerate(breaks) if val <= t), len(colors_purple) - 1)
                return {'fillColor': colors_purple[min(idx, len(colors_purple)-1)], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
            
            neets_layer = folium.FeatureGroup(name='Part NEETs 15-24 (INSEE) 2022', show=False)
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': valid_neets},
                style_function=neets_style,
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'neets'], aliases=['EPCI:', 'NEETs (%):'])
            ).add_to(neets_layer)
            neets_layer.add_to(m)
        
        # Sans diplome layer
        valid_diplome = [f for f in epci_enriched['features'] if f['properties'].get('sans_diplome_T') is not None and is_mainland_epci(f)]
        if valid_diplome:
            sorted_vals = sorted([f['properties']['sans_diplome_T'] for f in valid_diplome])
            n = len(sorted_vals)
            colors_green = ['#edf8e9', '#c7e9c0', '#a1d99b', '#74c476', '#41ab5d', '#238b45', '#005a32']
            breaks = [sorted_vals[int(n * i / len(colors_green))] for i in range(1, len(colors_green))]
            
            def diplome_style(feature):
                val = feature['properties'].get('sans_diplome_T')
                if val is None:
                    return {'fillColor': '#cccccc', 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.3}
                idx = next((i for i, t in enumerate(breaks) if val <= t), len(colors_green) - 1)
                return {'fillColor': colors_green[min(idx, len(colors_green)-1)], 'color': '#666666', 'weight': 0.5, 'fillOpacity': 0.6}
            
            diplome_layer = folium.FeatureGroup(name='Part +15 ans sans diplôme (INSEE) 2022', show=False)
            folium.GeoJson(
                {'type': 'FeatureCollection', 'features': valid_diplome},
                style_function=diplome_style,
                tooltip=folium.GeoJsonTooltip(fields=['libgeo', 'sans_diplome_T'], aliases=['EPCI:', 'Sans diplôme (%):'])
            ).add_to(diplome_layer)
            diplome_layer.add_to(m)
    
    # Add isochrone layers
    print("Adding isochrone layers...")
    locations_df = df[['title', 'lat', 'lng']].copy()
    locations_df['lat_key'] = locations_df['lat'].round(6)
    locations_df['lng_key'] = locations_df['lng'].round(6)
    unique_locations = locations_df.groupby(['lat_key', 'lng_key'], as_index=False).agg(titles=('title', lambda x: list(x)))
    
    duration_colors_car = {600: '#a6cee3', 900: '#6baed6', 1800: '#1f78b4', 2400: '#b2df8a', 2700: '#33a02c', 3600: '#fb9a99'}
    duration_colors_walk = {600: '#a1d99b', 900: '#31a354'}
    
    # Car isochrones
    for minutes, seconds in [(10, 600), (15, 900), (30, 1800), (40, 2400), (45, 2700), (60, 3600)]:
        features = []
        fill_color = duration_colors_car.get(seconds, '#4a90d9')
        for _, row in unique_locations.iterrows():
            lat, lng, titles = row['lat_key'], row['lng_key'], row['titles']
            cache_key = f"{lat:.6f}_{lng:.6f}_{seconds}_driving-car"
            if cache_key in isochrone_cache:
                coords = isochrone_cache[cache_key]
                if coords and len(coords) > 0:
                    label = titles[0] if len(titles) == 1 else f"{titles[0]} (+{len(titles)-1})"
                    features.append({"type": "Feature", "properties": {"name": label, "names": "<br>".join(titles)}, "geometry": {"type": "Polygon", "coordinates": coords}})
        if features:
            layer = folium.FeatureGroup(name=f"🚗 {minutes} min", show=False)
            folium.GeoJson({"type": "FeatureCollection", "features": features},
                style_function=lambda x, fc=fill_color: {'fillColor': fc, 'color': '#333', 'weight': 1, 'fillOpacity': 0.25},
                tooltip=folium.GeoJsonTooltip(fields=['names'], aliases=[''], labels=False, parse_html=True)
            ).add_to(layer)
            layer.add_to(m)
    
    # Walk isochrones
    for minutes, seconds in [(10, 600), (15, 900)]:
        features = []
        fill_color = duration_colors_walk.get(seconds, '#5cb85c')
        for _, row in unique_locations.iterrows():
            lat, lng, titles = row['lat_key'], row['lng_key'], row['titles']
            cache_key = f"{lat:.6f}_{lng:.6f}_{seconds}_foot-walking"
            if cache_key in isochrone_cache:
                coords = isochrone_cache[cache_key]
                if coords and len(coords) > 0:
                    label = titles[0] if len(titles) == 1 else f"{titles[0]} (+{len(titles)-1})"
                    features.append({"type": "Feature", "properties": {"name": label, "names": "<br>".join(titles)}, "geometry": {"type": "Polygon", "coordinates": coords}})
        if features:
            layer = folium.FeatureGroup(name=f"🚶 {minutes} min", show=False)
            folium.GeoJson({"type": "FeatureCollection", "features": features},
                style_function=lambda x, fc=fill_color: {'fillColor': fc, 'color': '#333', 'weight': 1, 'fillOpacity': 0.25},
                tooltip=folium.GeoJsonTooltip(fields=['names'], aliases=[''], labels=False, parse_html=True)
            ).add_to(layer)
            layer.add_to(m)
    
    # Add markers
    print("Adding markers...")
    markers_layer = folium.FeatureGroup(name='Établissements', show=True)
    for idx, row in df.iterrows():
        title, lat, lng = row['title'], row['lat'], row['lng']
        categorie = row.get('categorie', '') if 'categorie' in df.columns else ''
        main_cat = get_main_category(categorie)
        marker_color = get_marker_color(categorie)
        
        popup = f"""
        <div style="font-family:sans-serif;min-width:200px;">
            <div style="font-weight:600;font-size:13px;margin-bottom:4px;">{title}</div>
            <div style="background:{marker_color};color:white;padding:3px 8px;border-radius:4px;font-size:10px;display:inline-block;">{main_cat}</div>
            <div style="font-size:10px;color:#666;margin-top:4px;">{categorie}</div>
        </div>
        """
        
        pin_html = f'''
        <div style="position:relative;">
            <svg width="25" height="41" viewBox="0 0 25 41" xmlns="http://www.w3.org/2000/svg">
                <path fill="{marker_color}" stroke="#333" stroke-width="1" d="M12.5 0C5.6 0 0 5.6 0 12.5c0 2.4.7 4.7 1.9 6.6L12.5 41l10.6-21.9c1.2-1.9 1.9-4.2 1.9-6.6C25 5.6 19.4 0 12.5 0z"/>
                <circle fill="white" cx="12.5" cy="12.5" r="5"/>
            </svg>
        </div>
        '''
        icon = folium.DivIcon(html=pin_html, icon_size=(25, 41), icon_anchor=(12, 41), popup_anchor=(0, -35))
        
        folium.Marker(
            location=[lat, lng],
            popup=folium.Popup(popup, max_width=300),
            tooltip=f"{title} | {main_cat}",
            icon=icon
        ).add_to(markers_layer)
    
    markers_layer.add_to(m)
    
    # Add layer control
    folium.LayerControl(collapsed=False, position='topright').add_to(m)
    
    # Save to HTML
    output_path = os.path.join(SCRIPT_DIR, "map.html")
    print(f"Saving map to {output_path}...")
    m.save(output_path)
    print("Done!")
    
    # Print file size
    file_size = os.path.getsize(output_path) / (1024 * 1024)
    print(f"Map file size: {file_size:.2f} MB")

if __name__ == "__main__":
    generate_map()
