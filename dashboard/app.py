"""Flask dashboard for the NYC Social Heat Impact Index (SHII).

Usage:
    uv run dashboard/app.py
"""

import datetime as dt
import json
import logging
import os
import sys
import threading

import pandas as pd
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

load_dotenv()

# Make dashboard/ importable whether app.py is run as a script or imported by
# wsgi.py as dashboard.app.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_compute  # noqa: E402

log = logging.getLogger(__name__)

app = Flask(__name__)

APP_TOKEN = os.environ.get('NYC_OPEN_DATA_APP_TOKEN')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')


def _latest_available_date() -> str:
    """Most recent date the dashboard can show: yesterday.

    Recomputed on every request (never cached at import) so the date picker
    advances each day even though gunicorn keeps the process alive for weeks.
    The live pipeline in live_compute already serves fresh data for these dates.
    """
    return (dt.date.today() - dt.timedelta(days=1)).strftime('%Y-%m-%d')

# Last date for which EMS data is actually available in the source dataset.
# Dates after this show a warning and exclude EMS from scoring.
EMS_LAST_VALID_DATE = "2025-08-31"

# Date the picker opens on. Chosen before EMS_LAST_VALID_DATE so EMS is available
# (and stays checked) on load; the picker still extends to yesterday via date_max.
DATE_DEFAULT = "2025-06-24"

# Category definitions matching compute_shii() in basic_figs.ipynb
CATEGORIES = {
    'ems':         {'col': 'heat_ems_count_norm_last3', 'threshold': 0.5,  'label': 'Heat Emergencies (EMS)', 'color': '#E9C46A'},
    'hydrant':     {'col': 'hydrant_all_norm_last3',    'threshold': 8.6,  'label': 'Hydrant (311)',          'color': '#D62828'},
    'power':       {'col': 'power_norm_last3',          'threshold': 1.0,  'label': 'Power (311)',            'color': '#8338EC'},
    'ventilation': {'col': 'ventilation_norm_last3',    'threshold': 0.8,  'label': 'Ventilation (311)',      'color': '#FCBF49'},
    'ac':          {'col': 'ac_norm_last3',             'threshold': 0.0,  'label': 'AC (311)',               'color': '#2A9D8F'},
    'tree':        {'col': 'tree_norm_last3',           'threshold': 2.6,  'label': 'Tree Requests (311)',    'color': '#2DC653'},
}

# ── Load precomputed data on startup ──────────────────────────────────────────

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


roll_df, cdta_geojson, DATE_MIN, PRECOMPUTED_DATE_MAX = _load_data()

# The date picker extends to yesterday (see _latest_available_date); EMS is
# reliable only up to EMS_LAST_VALID_DATE.
PRECOMPUTED_DATE_MAX_TS = pd.Timestamp(PRECOMPUTED_DATE_MAX)


# ── Background precompute of live dates ───────────────────────────────────────

def _bg_precompute() -> None:
    """Fill the live cache for every date from PRECOMPUTED_DATE_MAX+1 → yesterday."""
    precomputed = dt.date.fromisoformat(PRECOMPUTED_DATE_MAX)
    yesterday = dt.date.today() - dt.timedelta(days=1)
    start = precomputed + dt.timedelta(days=1)
    if start > yesterday:
        log.info("live cache: precomputed data is already current, nothing to fetch")
        return
    log.info("live cache background precompute: %s → %s", start, yesterday)
    live_compute.precompute_range(APP_TOKEN, start, yesterday)


threading.Thread(target=_bg_precompute, daemon=True, name='live-precompute').start()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_live_response(cdta_vals: dict, selected: list[str]) -> dict:
    """Format live 311-only data into the same shape as the historical response."""
    data: dict = {}
    for cdta, vals in cdta_vals.items():
        flags: dict = {}
        for cat, cfg in CATEGORIES.items():
            if cat == 'ems':
                flags[cat] = 0
            else:
                flags[cat] = int(vals.get(cfg['col'], 0) > cfg['threshold'])

        shii_total = sum(flags[c] for c in selected if c in flags and c != 'ems')

        data[cdta] = {
            'shii_total': shii_total,
            'flags': flags,
            'vals': {
                cat: (
                    None if cat == 'ems'
                    else round(float(vals.get(CATEGORIES[cat]['col'], 0)), 2)
                )
                for cat in CATEGORIES
            },
        }
    return data


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    cats_for_template = {
        k: {'label': v['label'], 'threshold': v['threshold'], 'color': v['color']}
        for k, v in CATEGORIES.items()
    }
    latest = _latest_available_date()
    return render_template(
        'index.html',
        date_min=DATE_MIN,
        date_default=DATE_DEFAULT,
        date_max=latest,
        ems_cutoff=EMS_LAST_VALID_DATE,
        categories=cats_for_template,
    )


@app.route('/api/geometry')
def get_geometry():
    """Return community district polygons (fetched once by the client)."""
    return jsonify(cdta_geojson)


@app.route('/api/shii')
def get_shii():
    """Return per-CDTA SHII scores for a given date and category selection.

    Dates within the precomputed range (≤ PRECOMPUTED_DATE_MAX) are served from
    the parquet file.  More recent dates are served from the live 311 pipeline
    (EMS always 0/null there).
    """
    date_str = request.args.get('date', _latest_available_date())
    cats_param = request.args.get('categories', ','.join(CATEGORIES))
    selected = [c for c in cats_param.split(',') if c in CATEGORIES]

    try:
        target = pd.Timestamp(date_str)
    except Exception:
        return jsonify({'error': 'Invalid date'}), 400

    # ── Live path (date beyond precomputed data) ───────────────────────────
    if target > PRECOMPUTED_DATE_MAX_TS:
        try:
            cdta_vals = live_compute.get_live_data(APP_TOKEN, date_str)
        except Exception as exc:
            log.exception("live_compute failed for %s", date_str)
            return jsonify({'error': str(exc)}), 500

        tmax = live_compute.get_live_tmax(date_str)

        if not cdta_vals:
            return jsonify({'date': date_str, 'tmax': tmax, 'data': {}, 'live': True})

        data = _format_live_response(cdta_vals, selected)
        return jsonify({'date': date_str, 'tmax': tmax, 'data': data, 'live': True})

    # ── Historical path ────────────────────────────────────────────────────
    day = roll_df[roll_df['date'] == target].copy()
    if day.empty:
        return jsonify({'date': date_str, 'tmax': None, 'data': {}})

    for cat, cfg in CATEGORIES.items():
        day[f'flag_{cat}'] = (day[cfg['col']] > cfg['threshold']).astype(int)

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
