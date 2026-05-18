#!/usr/bin/env python3
"""Precompute SHII rolling data and save to disk.

If data/roll_df.parquet already exists, skips the historical pipeline and only
fetches new dates from the 311 API (up to today).  On a fresh install (no
parquet), runs the full historical pipeline from examples/311_calls.gpkg and
examples/ems_calls.csv first, then extends with live API data.

Run before starting app.py:
    uv run dashboard/precompute.py
"""

import os
import sys
import datetime as dt

import pandas as pd
import geopandas as gpd
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shii
import live_compute

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
EXAMPLES_DIR = os.path.join(os.path.dirname(__file__), '..', 'examples')

ROLLING_DAYS = 3
ROLLING_COLUMNS = [
    'heat_ems_count', 'heat_ems_count_norm',
    'ac', 'ac_norm',
    'fhe', 'fhe_norm',
    'hydrant', 'hydrant_norm',
    'hydrant_all', 'hydrant_all_norm',
    'power', 'power_norm',
    'ventilation', 'ventilation_norm',
    'tree', 'tree_norm',
]


def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    out_parquet = os.path.join(DATA_DIR, 'roll_df.parquet')
    out_geojson = os.path.join(DATA_DIR, 'cdta.geojson')

    if os.path.exists(out_parquet):
        print(f"Parquet found — skipping historical pipeline.")
        save_df = pd.read_parquet(out_parquet)
        save_df['date'] = pd.to_datetime(save_df['date'])
        save_df['cdta'] = save_df['cdta'].astype(str)
        print(f"  Loaded {len(save_df):,} rows, {save_df['date'].min().date()} → {save_df['date'].max().date()}")
    else:
        print("No parquet found — running full historical pipeline from static cache files.")
        save_df = _build_historical(out_parquet)

    if not os.path.exists(out_geojson):
        print("Downloading community district geometry...")
        cdta_gdf = shii.download_community_districts().rename(columns={'boro_cd': 'cdta'})
        cdta_gdf = cdta_gdf[['cdta', 'geometry']]
        if cdta_gdf.crs is None:
            cdta_gdf = cdta_gdf.set_crs('EPSG:4326')
        else:
            cdta_gdf = cdta_gdf.to_crs('EPSG:4326')
        cdta_gdf['cdta'] = cdta_gdf['cdta'].astype(str)
        cdta_gdf.to_file(out_geojson, driver='GeoJSON')
        print(f"Saved geometry   → {out_geojson}  ({len(cdta_gdf)} districts)")

    _extend_with_live_data(out_parquet, save_df)


def _build_historical(out_parquet: str) -> pd.DataFrame:
    """Build roll_df.parquet from static cache files (311_calls.gpkg + ems_calls.csv)."""
    print("Loading 311 data from cache...")
    all_311_df = gpd.read_file(os.path.join(EXAMPLES_DIR, '311_calls.gpkg'))
    all_311_df['date'] = pd.to_datetime(all_311_df['date'])
    if all_311_df.crs is None:
        all_311_df = all_311_df.set_crs('EPSG:4326')

    print("Loading EMS data from cache...")
    heat_inc_df = pd.read_csv(os.path.join(EXAMPLES_DIR, 'ems_calls.csv'))

    print("Running pipeline (downloads weather + HVI + zone boundaries)...")
    full_df = shii.preprocess_merge_df(heat_inc_df, all_311_df, summer_only=False)

    full_df['hydrant_all'] = full_df['hydrant'] + full_df['fhe']
    pop = full_df['population'].replace(0, float('nan'))
    for col in ['ac', 'hydrant', 'hydrant_all', 'power', 'ventilation', 'fhe', 'heat_ems_count', 'tree']:
        full_df[f'{col}_norm'] = 100_000 * full_df[col] / pop
    full_df = full_df.fillna(0)

    print("Computing 3-day rolling sums...")
    heat_rolling = shii.compute_rolling(
        full_df, ROLLING_COLUMNS, window=dt.timedelta(days=ROLLING_DAYS)
    )
    heat_rolling = heat_rolling.reset_index().set_index(['cdta', 'date'])
    roll_df = full_df.join(heat_rolling, rsuffix='_last3')

    shii_cols = [
        'hydrant_all_norm_last3', 'ventilation_norm_last3', 'ac_norm_last3',
        'heat_ems_count_norm_last3', 'power_norm_last3', 'tree_norm_last3',
    ]
    display_cols = [
        'tmax',
        'hydrant_all_norm', 'ventilation_norm', 'ac_norm',
        'heat_ems_count_norm', 'power_norm', 'tree_norm',
    ]

    save_df = roll_df[shii_cols + display_cols + ['population']].reset_index()
    save_df['date'] = pd.to_datetime(save_df['date'])
    save_df['cdta'] = save_df['cdta'].astype(str)

    save_df.to_parquet(out_parquet, index=False)
    print(f"Saved roll data  → {out_parquet}")
    print(f"  Date range: {save_df['date'].min().date()} → {save_df['date'].max().date()}")
    print(f"  Rows: {len(save_df):,}")
    return save_df

    print("\nDone! Run  uv run dashboard/app.py  to start the server.")


def _extend_with_live_data(out_parquet: str, save_df: pd.DataFrame) -> None:
    """Fetch live 311 data for dates after the parquet's last date through today and append."""
    app_token = os.environ.get('NYC_OPEN_DATA_APP_TOKEN')

    last_date = save_df['date'].max().date()
    today = dt.date.today()
    start = last_date + dt.timedelta(days=1)

    if start > today:
        print("Parquet is already current through today.")
        return

    print(f"Fetching live 311 data {start} → {today}...")
    result = live_compute._fetch_and_process(app_token, start, today)
    if not result:
        print("No live data returned.")
        return

    pop_series = save_df.groupby('cdta')['population'].first()

    tmax_by_date: dict = {}
    try:
        weather_df = shii.download_weather(f"{start}T00:00:00", f"{today}T23:59:59")
        if not weather_df.empty and 'tmax' in weather_df.columns:
            for idx, row in weather_df.iterrows():
                t = row['tmax']
                tmax_by_date[idx.strftime('%Y-%m-%d')] = (
                    round(float(t), 1) if t is not None and not pd.isna(t) else None
                )
    except Exception as exc:
        print(f"  Warning: weather fetch failed ({exc}); tmax will be null for live dates")

    live_rows = []
    for date_str, cdta_data in result.items():
        tmax = tmax_by_date.get(date_str)
        for cdta_str, vals in cdta_data.items():
            live_rows.append({
                'cdta': cdta_str,
                'date': pd.Timestamp(date_str),
                'hydrant_all_norm_last3': vals.get('hydrant_all_norm_last3', 0.0),
                'ventilation_norm_last3': vals.get('ventilation_norm_last3', 0.0),
                'ac_norm_last3':          vals.get('ac_norm_last3', 0.0),
                'heat_ems_count_norm_last3': 0.0,
                'power_norm_last3':       vals.get('power_norm_last3', 0.0),
                'tree_norm_last3':        vals.get('tree_norm_last3', 0.0),
                'tmax': tmax,
                'hydrant_all_norm': 0.0,
                'ventilation_norm': 0.0,
                'ac_norm': 0.0,
                'heat_ems_count_norm': 0.0,
                'power_norm': 0.0,
                'tree_norm': 0.0,
                'population': float(pop_series.get(cdta_str, 0)),
            })

    live_df = pd.DataFrame(live_rows)
    combined = pd.concat([save_df, live_df], ignore_index=True)
    combined.to_parquet(out_parquet, index=False)
    print(f"Appended {len(result)} live date(s) ({start} → {today})")
    print(f"  Updated date range: {combined['date'].min().date()} → {combined['date'].max().date()}")
    print(f"  Rows: {len(combined):,}")


if __name__ == '__main__':
    main()
