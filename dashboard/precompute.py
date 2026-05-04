#!/usr/bin/env python3
"""Precompute SHII rolling data from cached 311 and EMS files and save to disk.

Run this once before starting app.py:
    uv run dashboard/precompute.py
"""

import os
import sys
import datetime as dt

import pandas as pd
import geopandas as gpd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import shii

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

    print("Loading 311 data from cache...")
    all_311_df = gpd.read_file(os.path.join(EXAMPLES_DIR, '311_calls.gpkg'))
    all_311_df['date'] = pd.to_datetime(all_311_df['date'])
    if all_311_df.crs is None:
        all_311_df = all_311_df.set_crs('EPSG:4326')

    print("Loading EMS data from cache...")
    heat_inc_df = pd.read_csv(os.path.join(EXAMPLES_DIR, 'ems_calls.csv'))

    print("Running pipeline (downloads weather + HVI + zone boundaries)...")
    full_df = shii.preprocess_merge_df(heat_inc_df, all_311_df, summer_only=False)

    # hydrant_all and normalised columns (same as notebook)
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

    save_df = roll_df[shii_cols + display_cols].reset_index()
    save_df['date'] = pd.to_datetime(save_df['date'])
    save_df['cdta'] = save_df['cdta'].astype(str)

    out_parquet = os.path.join(DATA_DIR, 'roll_df.parquet')
    save_df.to_parquet(out_parquet, index=False)
    print(f"Saved roll data  → {out_parquet}")
    print(f"  Date range: {save_df['date'].min().date()} → {save_df['date'].max().date()}")
    print(f"  Rows: {len(save_df):,}")

    print("Downloading community district geometry...")
    cdta_gdf = shii.download_community_districts().rename(columns={'boro_cd': 'cdta'})
    cdta_gdf = cdta_gdf[['cdta', 'geometry']]
    if cdta_gdf.crs is None:
        cdta_gdf = cdta_gdf.set_crs('EPSG:4326')
    else:
        cdta_gdf = cdta_gdf.to_crs('EPSG:4326')
    cdta_gdf['cdta'] = cdta_gdf['cdta'].astype(str)

    out_geojson = os.path.join(DATA_DIR, 'cdta.geojson')
    cdta_gdf.to_file(out_geojson, driver='GeoJSON')
    print(f"Saved geometry   → {out_geojson}  ({len(cdta_gdf)} districts)")

    print("\nDone! Run  uv run dashboard/app.py  to start the server.")


if __name__ == '__main__':
    main()
