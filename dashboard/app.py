"""Flask dashboard for the NYC Social Heat Impact Index (SHII).

Usage:
    uv run dashboard/app.py
"""

import json
import os

import pandas as pd
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DATE_DEFAULT = "2024-06-20"

# Category definitions matching compute_shii() in basic_figs.ipynb
CATEGORIES = {
    'hydrant':     {'col': 'hydrant_all_norm_last3',    'threshold': 8.6,  'label': 'Hydrant (311)',     'color': '#D62828'},
    'ems':         {'col': 'heat_ems_count_norm_last3', 'threshold': 0.5,  'label': 'Heat Emergencies (EMS)', 'color': '#E9C46A'},
    'ac':          {'col': 'ac_norm_last3',             'threshold': 0.0,  'label': 'AC (311)',           'color': '#2A9D8F'},
    'power':       {'col': 'power_norm_last3',          'threshold': 1.0,  'label': 'Power (311)',        'color': '#8338EC'},
    'tree':        {'col': 'tree_norm_last3',           'threshold': 2.6,  'label': 'Tree Requests (311)',         'color': '#2DC653'},
    'ventilation': {'col': 'ventilation_norm_last3',    'threshold': 0.8,  'label': 'Ventilation (311)', 'color': '#FCBF49'},
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
    with open(geojson_path) as f:
        geojson = json.load(f)

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
        date_default=DATE_DEFAULT,
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
    date_str = request.args.get('date', DATE_DEFAULT)
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


@app.route('/api/timeline')
def get_timeline():
    """Return daily SHII scores for one CDTA over a full year."""
    cdta = request.args.get('cdta', '')
    year = request.args.get('year', type=int)
    cats_param = request.args.get('categories', ','.join(CATEGORIES))
    selected = [c for c in cats_param.split(',') if c in CATEGORIES]

    if not cdta or not year:
        return jsonify({'error': 'cdta and year required'}), 400

    mask = (roll_df['cdta'] == cdta) & (roll_df['date'].dt.year == year)
    df = roll_df[mask].copy()
    if df.empty:
        return jsonify({'cdta': cdta, 'year': year, 'data': []})

    for cat, cfg in CATEGORIES.items():
        df[f'flag_{cat}'] = (df[cfg['col']] > cfg['threshold']).astype(int)

    df['shii_total'] = df[[f'flag_{c}' for c in selected]].sum(axis=1) if selected else 0

    data = [
        {
            'date': row['date'].strftime('%Y-%m-%d'),
            'shii': int(row['shii_total']),
            'tmax': round(float(row['tmax']), 1) if not pd.isna(row['tmax']) else None,
        }
        for _, row in df.sort_values('date').iterrows()
    ]
    return jsonify({'cdta': cdta, 'year': year, 'data': data})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
