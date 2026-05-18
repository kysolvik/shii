"""Live 311 data pipeline for dates beyond the precomputed parquet range.

Two modes:
  • precompute_range() — called once at startup in a background thread; fetches
    the entire gap (PRECOMPUTED_DATE_MAX+1 → yesterday) in one batch per type.
  • get_live_data()    — on-demand fallback for any date not yet in the cache;
    also used when a user navigates to a date before the bulk job finishes.

All results are cached by date string and cleared when the calendar day rolls
over (yesterday has changed, so rolling sums change too).
"""

import datetime as dt
import logging
import os
import sys
import threading

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
import shii
from shii._data_helpers import CDTA_BOROUGH_LOOKUP

log = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
ROLLING_DAYS = 3

# ── Shared mutable state ──────────────────────────────────────────────────────

_lock = threading.Lock()
_state: dict = {
    'cache': {},        # {date_str: {cdta_str: {norm_last3_col: float}}}
    'cache_day': None,  # str date "YYYY-MM-DD"; cache is valid only on this day
}

_pop_lock = threading.Lock()
_pop: dict = {'series': None}   # pd.Series once loaded

_weather_lock = threading.Lock()
_weather_state: dict = {
    'cache': {},        # {date_str: float | None}
    'cache_day': None,
}


# ── Population ────────────────────────────────────────────────────────────────

def _get_population(app_token: str | None) -> pd.Series:
    with _pop_lock:
        if _pop['series'] is not None:
            return _pop['series']

        roll_path = os.path.join(DATA_DIR, 'roll_df.parquet')
        roll_df = pd.read_parquet(roll_path)
        if 'population' in roll_df.columns:
            _pop['series'] = roll_df.groupby('cdta')['population'].first().astype(float)
            return _pop['series']

        # Fallback: download from NYC Open Data
        log.info("population not in roll_df.parquet — downloading from API")
        pop_raw = shii.download_cd_population(app_token=app_token)
        pop_raw['borough_code'] = pop_raw['borough'].map(CDTA_BOROUGH_LOOKUP)
        pop_raw['cdta'] = (
            pop_raw['borough_code'].astype(str) + pop_raw['cd_number'].str.zfill(2)
        )
        _pop['series'] = pop_raw.set_index('cdta')['_2010_population'].astype(float)
        return _pop['series']


# ── Core processing ───────────────────────────────────────────────────────────

def _process_311_batch(
    all_311: pd.DataFrame,
    cdta_gdf: gpd.GeoDataFrame,
    pop: pd.Series,
    target_dates,           # sequence of date/Timestamp objects
    roll_window_start: dt.date,
) -> dict:
    """Spatial join → normalise → rolling sum → extract one result dict per date.

    Returns {date_str: {cdta_str: {norm_last3 col: float}}}.
    """
    all_311 = all_311.copy()
    all_311['longitude'] = pd.to_numeric(all_311['longitude'], errors='coerce')
    all_311['latitude'] = pd.to_numeric(all_311['latitude'], errors='coerce')
    all_311 = all_311.dropna(subset=['longitude', 'latitude'])

    all_311_gdf = gpd.GeoDataFrame(
        all_311,
        geometry=[Point(xy) for xy in zip(all_311['longitude'], all_311['latitude'])],
        crs='EPSG:4326',
    )
    joined = all_311_gdf.sjoin(cdta_gdf[['geometry', 'cdta']], how='inner')
    joined.loc[
        joined['descriptor'] == 'Fire Hydrant Emergency (FHE)', 'request_type'
    ] = 'fhe'
    joined['date'] = pd.to_datetime(joined['created_date']).dt.normalize()

    counts = (
        joined
        .groupby(['cdta', 'date', 'request_type'])
        .size()
        .reset_index(name='n')
    )
    pivot = counts.pivot_table(
        index=['cdta', 'date'], columns='request_type', values='n', fill_value=0
    )
    pivot.columns.name = None
    for col in ['hydrant', 'fhe', 'ac', 'ventilation', 'power', 'tree']:
        if col not in pivot.columns:
            pivot[col] = 0.0
    pivot['hydrant_all'] = pivot['hydrant'] + pivot['fhe']

    # Full grid: every CDTA × every date from roll_window_start → latest target
    all_cdtas = cdta_gdf['cdta'].unique()
    max_target = max(pd.Timestamp(d) for d in target_dates)
    full_date_range = pd.date_range(str(roll_window_start), max_target, freq='D')
    full_idx = pd.MultiIndex.from_product(
        [all_cdtas, full_date_range], names=['cdta', 'date']
    )
    pivot = pivot.reindex(full_idx, fill_value=0).reset_index()

    pop_df = pop.rename('population').reset_index()
    pop_df['cdta'] = pop_df['cdta'].astype(str)
    pivot = pivot.merge(pop_df, on='cdta', how='left')
    pop_safe = pivot['population'].replace(0, float('nan'))
    for col in ['hydrant_all', 'ac', 'ventilation', 'power', 'tree']:
        pivot[f'{col}_norm'] = 100_000.0 * pivot[col] / pop_safe
    pivot = pivot.fillna(0)

    norm_cols = [
        'hydrant_all_norm', 'ac_norm', 'ventilation_norm',
        'power_norm', 'tree_norm',
    ]
    rolling = shii.compute_rolling(
        pivot.set_index(['cdta', 'date']),
        norm_cols,
        window=dt.timedelta(days=ROLLING_DAYS),
    )
    rolling = rolling.reset_index()

    empty_row = {
        'hydrant_all_norm_last3': 0.0,
        'ac_norm_last3': 0.0,
        'ventilation_norm_last3': 0.0,
        'power_norm_last3': 0.0,
        'tree_norm_last3': 0.0,
    }
    result: dict = {}
    for target in target_dates:
        target_ts = pd.Timestamp(target)
        date_str = target_ts.strftime('%Y-%m-%d')
        yest = rolling[rolling['date'] == target_ts].set_index('cdta')
        yest = yest[~yest.index.duplicated(keep='first')]

        date_data: dict = {}
        for cdta in all_cdtas:
            cdta_str = str(cdta)
            if cdta_str in yest.index:
                row = yest.loc[cdta_str]
                date_data[cdta_str] = {
                    'hydrant_all_norm_last3': round(float(row['hydrant_all_norm']), 2),
                    'ac_norm_last3':          round(float(row['ac_norm']), 2),
                    'ventilation_norm_last3': round(float(row['ventilation_norm']), 2),
                    'power_norm_last3':       round(float(row['power_norm']), 2),
                    'tree_norm_last3':        round(float(row['tree_norm']), 2),
                }
            else:
                date_data[cdta_str] = empty_row.copy()
        result[date_str] = date_data

    return result


def _fetch_and_process(
    app_token: str | None,
    start_date: dt.date,
    end_date: dt.date,
) -> dict:
    """Download 311 data and compute rolling sums for all dates in [start, end]."""
    # Pull ROLLING_DAYS-1 extra days before start so the first date has a full window
    roll_window_start = start_date - dt.timedelta(days=ROLLING_DAYS - 1)
    fetch_end = end_date + dt.timedelta(days=1)  # exclusive upper bound for API

    log.info("fetching 311 data %s → %s", roll_window_start, end_date)

    frames = []
    for rt in ['hydrant', 'ac', 'ventilation', 'power', 'tree']:
        df = shii.download_311_requests(
            request_type=rt,
            app_token=app_token,
            start_timestamp=f"{roll_window_start}T00:00:00",
            end_timestamp=f"{fetch_end}T00:00:00",
            limit=2_000_000,
        )
        if not df.empty:
            df['request_type'] = rt
            frames.append(df)

    if not frames:
        log.warning("no 311 data for %s → %s", start_date, end_date)
        return {}

    all_311 = pd.concat(frames, ignore_index=True)
    cdta_gdf = gpd.read_file(os.path.join(DATA_DIR, 'cdta.geojson'))
    cdta_gdf['cdta'] = cdta_gdf['cdta'].astype(str)
    pop = _get_population(app_token)

    target_dates = pd.date_range(str(start_date), str(end_date), freq='D')
    return _process_311_batch(all_311, cdta_gdf, pop, target_dates, roll_window_start)


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _ensure_fresh_cache(today: str) -> None:
    """Clear cache if the calendar day has rolled over. Must be called under _lock."""
    if _state['cache_day'] != today:
        _state['cache'].clear()
        _state['cache_day'] = today


# ── Weather ───────────────────────────────────────────────────────────────────

def _prefetch_weather(start_date: dt.date, end_date: dt.date) -> None:
    """Download weather for a date range and populate the weather cache."""
    try:
        weather_df = shii.download_weather(
            f"{start_date}T00:00:00",
            f"{end_date}T23:59:59",
        )
        today = str(dt.date.today())
        with _weather_lock:
            if _weather_state['cache_day'] != today:
                _weather_state['cache'].clear()
                _weather_state['cache_day'] = today
            for idx, row in weather_df.iterrows():
                date_str = idx.strftime('%Y-%m-%d')
                tmax = row.get('tmax')
                _weather_state['cache'][date_str] = (
                    round(float(tmax), 1)
                    if tmax is not None and not pd.isna(tmax)
                    else None
                )
    except Exception:
        log.exception("weather prefetch failed for %s → %s", start_date, end_date)


def get_live_tmax(date_str: str) -> 'float | None':
    """Return max temperature for a live date, fetching from Meteostat if needed."""
    today = str(dt.date.today())
    with _weather_lock:
        if _weather_state['cache_day'] != today:
            _weather_state['cache'].clear()
            _weather_state['cache_day'] = today
        if date_str in _weather_state['cache']:
            return _weather_state['cache'][date_str]

    # On-demand single-day fetch
    try:
        target = dt.date.fromisoformat(date_str)
        weather_df = shii.download_weather(
            f"{target}T00:00:00",
            f"{target}T23:59:59",
        )
        if not weather_df.empty and 'tmax' in weather_df.columns:
            tmax = weather_df['tmax'].iloc[0]
            result = round(float(tmax), 1) if not pd.isna(tmax) else None
        else:
            result = None
    except Exception:
        log.exception("weather fetch failed for %s", date_str)
        result = None

    with _weather_lock:
        if _weather_state['cache_day'] == today:
            _weather_state['cache'][date_str] = result

    return result


# ── Public API ────────────────────────────────────────────────────────────────

def precompute_range(
    app_token: str | None,
    start_date: dt.date,
    end_date: dt.date,
) -> None:
    """Fetch and cache all dates in [start_date, end_date] in one batch.

    Intended to be called once at startup in a daemon thread so historical
    live dates load instantly for the rest of the day.
    """
    if end_date < start_date:
        return
    log.info("bulk precompute starting: %s → %s", start_date, end_date)
    try:
        result = _fetch_and_process(app_token, start_date, end_date)
    except Exception:
        log.exception("precompute_range failed")
        return

    today = str(dt.date.today())
    with _lock:
        _ensure_fresh_cache(today)
        _state['cache'].update(result)
    log.info("bulk precompute done: %d dates cached", len(result))

    _prefetch_weather(start_date, end_date)


def get_live_data(app_token: str | None, target_date: str) -> dict:
    """Return {cdta_str: norm_last3_cols} for target_date.

    Checks the shared cache first (populated by precompute_range).  If the
    date is not cached yet (bulk job still running or not triggered), fetches
    just that date on-demand and adds the result to the cache.
    """
    today = str(dt.date.today())
    with _lock:
        _ensure_fresh_cache(today)
        if target_date in _state['cache']:
            return _state['cache'][target_date]

    # On-demand fetch for this single date
    target = dt.date.fromisoformat(target_date)
    result = _fetch_and_process(app_token, target, target)
    data = result.get(target_date, {})

    with _lock:
        if _state['cache_day'] == today:   # still the same day
            _state['cache'][target_date] = data

    return data
