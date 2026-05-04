"""Flask dashboard for the NYC Summer Heat Impact Index (SHII).

Usage:
    uv run dashboard/app.py
"""

import json
import os

import pandas as pd
import geopandas as gpd
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

# Category definitions matching compute_shii() in basic_figs.ipynb
CATEGORIES = {
    'hydrant':     {'col': 'hydrant_all_norm_last3',    'threshold': 8.6,  'label': 'Hydrant (311)',     'color': '#D62828'},
    'ventilation': {'col': 'ventilation_norm_last3',    'threshold': 0.8,  'label': 'Ventilation (311)', 'color': '#FCBF49'},
    'ac':          {'col': 'ac_norm_last3',             'threshold': 0.0,  'label': 'AC (311)',           'color': '#2A9D8F'},
    'ems':         {'col': 'heat_ems_count_norm_last3', 'threshold': 0.5,  'label': 'Heat EMS',           'color': '#E9C46A'},
    'power':       {'col': 'power_norm_last3',          'threshold': 1.0,  'label': 'Power (311)',        'color': '#8338EC'},
    'tree':        {'col': 'tree_norm_last3',           'threshold': 2.6,  'label': 'Tree (311)',         'color': '#2DC653'},
}

# ── Load data on startup ──────────────────────────────────────────────────────

def _load_data():
    parquet_path = os.path.join(DATA_DIR, 'roll_df.parquet')
    geojson_path = os.path.join(DATA_DIR, 'cdta.geojson')
    if not os.path.exists(parquet_path) or not os.path.exists(geojson_path):
        raise FileNotFoundError(
            "Precomputed data not found. Run  uv run dashboard/precompute.py  first."
        )

    print("Loading precomputed roll data...")
    df = pd.read_parquet(parquet_path)
    df['date'] = pd.to_datetime(df['date'])
    df['cdta'] = df['cdta'].astype(str)

    print("Loading community district geometry...")
    gdf = gpd.read_file(geojson_path)
    gdf['cdta'] = gdf['cdta'].astype(str)
    geojson = json.loads(gdf[['cdta', 'geometry']].to_json())

    date_min = df['date'].min().strftime('%Y-%m-%d')
    date_max = df['date'].max().strftime('%Y-%m-%d')
    print(f"Ready — date range {date_min} → {date_max}, {len(df):,} rows")
    return df, geojson, date_min, date_max


roll_df, cdta_geojson, DATE_MIN, DATE_MAX = _load_data()

# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    cats_for_template = {
        k: {'label': v['label'], 'threshold': v['threshold'], 'color': v['color']}
        for k, v in CATEGORIES.items()
    }
    return render_template(
        'index.html',
        date_min=DATE_MIN,
        date_max=DATE_MAX,
        categories=cats_for_template,
    )


@app.route('/api/geometry')
def get_geometry():
    """Return community district polygons (fetched once by the client)."""
    return jsonify(cdta_geojson)


@app.route('/api/shii')
def get_shii():
    """Return per-CDTA SHII scores for a given date and category selection."""
    date_str = request.args.get('date', DATE_MAX)
    cats_param = request.args.get('categories', ','.join(CATEGORIES))
    selected = [c for c in cats_param.split(',') if c in CATEGORIES]

    try:
        target = pd.Timestamp(date_str)
    except Exception:
        return jsonify({'error': 'Invalid date'}), 400

    day = roll_df[roll_df['date'] == target].copy()
    if day.empty:
        return jsonify({'date': date_str, 'tmax': None, 'data': {}})

    # Compute flags for all categories (so the tooltip can show unselected ones too)
    for cat, cfg in CATEGORIES.items():
        day[f'flag_{cat}'] = (day[cfg['col']] > cfg['threshold']).astype(int)

    # SHII total counts only selected categories
    if selected:
        day['shii_total'] = day[[f'flag_{c}' for c in selected]].sum(axis=1)
    else:
        day['shii_total'] = 0

    tmax = day['tmax'].mean()
    tmax = round(float(tmax), 1) if not pd.isna(tmax) else None

    data = {}
    for _, row in day.iterrows():
        cdta = str(row['cdta'])
        data[cdta] = {
            'shii_total': int(row['shii_total']),
            'flags': {cat: int(row[f'flag_{cat}']) for cat in CATEGORIES},
            'vals': {
                cat: round(float(row[CATEGORIES[cat]['col']]), 2)
                for cat in CATEGORIES
            },
        }

    return jsonify({'date': date_str, 'tmax': tmax, 'data': data})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
