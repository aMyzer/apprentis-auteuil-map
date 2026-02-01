# Outil de Dataviz - Apprentis d'Auteuil

Application Streamlit de visualisation géographique des établissements des Apprentis d'Auteuil en France métropolitaine.

## Fonctionnalités

- **Carte interactive** des établissements avec marqueurs colorés par catégorie
- **Indicateurs INSEE** (2022) : 
  - Taux de chômage par EPCI
  - Taux de pauvreté par EPCI
  - Part des NEETs 15-24 ans
  - Part des +15 ans sans diplôme
- **Quartiers Prioritaires de la Ville (QPV)** avec coloration des EPCI selon le nombre de QPV
- **Zones d'accessibilité (isochrones)** : 10, 15, 30, 40, 45, 60 min en voiture et 10, 15 min à pied

## Catégories d'établissements

- **Formation** : 1er degré, Collège, Lycée pro, Lycée pro agricole, Post-bac
- **Protection de l'enfance** : MECs MNA, MECs Fratrie, MECs AEMO, MECs Semi-autonomie
- **Insertion** : Dispositifs d'insertion, IAE
- **Parentalité** : Maison des familles, Crèches, Autres dispositifs

## Déploiement sur Streamlit Cloud

1. Fork ce repository sur GitHub
2. Connectez-vous à [Streamlit Cloud](https://streamlit.io/cloud)
3. Cliquez sur "New app" et sélectionnez votre repository
4. Configurez :
   - Main file path: `app.py`
   - Python version: 3.11+
5. **Configurer les secrets** (Settings > Secrets) :
   ```toml
   MAPBOX_TOKEN = "pk.your_mapbox_token_here"
   ```

> **Note** : Les isochrones sont pré-calculés dans `isochrone_cache.json`. Le token Mapbox n'est nécessaire que pour les nouvelles requêtes d'isochrones à la demande.

## Fichiers de données

- `Draft etablissements_categorized.csv` : Liste des établissements avec catégorisation
- `epci_2025_complete.geojson` : Contours des EPCI (2025)
- `QP2024_France_Hexagonale_Outre_Mer_WGS84.geojson` : Quartiers prioritaires
- `isochrone_cache.json` : Cache des zones d'accessibilité (Mapbox)
- `taux_chomage_epci.csv`, `taux_pauvrete_epci.csv`, etc. : Indicateurs INSEE

## Installation locale

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Sources de données

- **EPCI** : OpenDataSoft / data.gouv.fr (2025)
- **QPV** : ANCT (2024)
- **Indicateurs INSEE** : INSEE (2022)
- **Isochrones** : Mapbox API
