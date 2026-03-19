"""Module to prepare and merge all 311 request data into a GeoPackage."""

import pandas as pd
import geopandas as gpd
from shapely import Point
import warnings
import os

from shii import _311, _weather, _ems, _misc, _zones


CDTA_BOROUGH_LOOKUP = {
    'MN':1,
    'Manhattan': 1,
    'BX': 2,
    'Bronx': 2,
    'BK': 3,
    'Brooklyn': 3,
    'QN': 4,
    'Queens': 4,
    'SI': 5,
    'Staten Island': 5
}

def convert_to_gdf(df, lon_col='longitude', lat_col='latitude', crs='EPSG:4326'):
    """Convert a DataFrame with longitude and latitude columns to a GeoDataFrame."""
    geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
    return gdf

def prepare_all_311_requests(app_token, year_range=range(2010, 2026), output_path='311_calls.gpkg'):
    """
    Download, process, and merge 311 request data for multiple types and years.

    Parameters
    ----------
    app_token : str
        NYC Open Data API token.
    year_range : range, optional
        Range of years to download data for. Default is 2010 to 2025.
    output_path : str, optional
        Path to save the output GeoPackage. Default is '311_calls.gpkg'.

    Returns
    -------
    gpd.GeoDataFrame
        GeoDataFrame containing all merged 311 requests with geometry and datetime columns.
    """

    if os.path.isfile(output_path):
        warnings.warn('output_path already exists. Reading and returning.\n'
                      'To create new download, either delete file or specify different output')
        all_requests_df =  gpd.read_file(output_path)
    else:
        request_types = ['hydrant', 'ac', 'ventilation', 'power']

        # Dictionary to hold dataframes for each request type
        request_dfs = {}

        for request_type in request_types:
            print(f"Downloading {request_type} requests...")
            request_list = []
            for y in year_range:
                incidents = _311.download_311_requests(
                    app_token=app_token,
                    request_type=request_type,
                    limit=1000000,
                    start_timestamp=f"{y}-01-01T00:00:00",
                    end_timestamp=f"{y}-12-31T23:59:59"
                )
                print(f"  Year {y}: {incidents.shape[0]} records")
                request_list.append(incidents)
            df = pd.concat(request_list, ignore_index=True)
            # Convert to GeoDataFrame
            df = convert_to_gdf(df)
            df['request_type'] = request_type
            request_dfs[request_type] = df

        # Concatenate all request types
        all_requests_df = pd.concat(list(request_dfs.values()), ignore_index=True)

        # Add datetime columns
        all_requests_df['datetime'] = pd.to_datetime(all_requests_df['created_date'])
        all_requests_df['date'] = pd.to_datetime(all_requests_df['datetime'].dt.date)
        all_requests_df['doy'] = all_requests_df['datetime'].dt.dayofyear

        # Save to GeoPackage
        all_requests_df.to_file(output_path, driver='GPKG')
        print(f"Saved {all_requests_df.shape[0]} records to {output_path}")

    return all_requests_df


def prepare_ems_calls(app_token, year_range=range(2010, 2026), output_path='ems_calls.csv'):
    """
    Download EMS calls for heat incidents

    Parameters
    ----------
    app_token : str
        NYC Open Data API token.
    year_range : range, optional
        Range of years to download data for. Default is 2010 to 2025.
    output_path : str, optional
        Path to save the output GeoPackage. Default is 'ems_calls.csv'.

    Returns
    -------
    pd.DataFrame
        DataFrame containing all EMS heat incidents
    """

    if os.path.isfile(output_path):
        warnings.warn('output_path already exists. Reading and returning.\n'
                      'To create new download, either delete file or specify different output')
        heat_df =  pd.read_csv(output_path)
    else:
        heat_list = []
        for y in year_range:
            heat_incidents = _ems.download_heat_incidents(
                app_token=app_token,
                limit=1000000,
                start_timestamp=f"{y}-01-01T00:00:00",
                end_timestamp=f"{y}-12-31T23:59:59"
            )
            print(y, heat_incidents.shape)
            heat_list.append(heat_incidents)
        heat_df = pd.concat(heat_list, ignore_index=True)
        heat_df.to_csv('ems_calls.csv', index=False)

    return heat_df


def compute_rolling(df, variables, window, metric='sum'):
    group_roll_df = (df
                     .reset_index()
                     .set_index('date')
                     .groupby('cdta')[variables]
                     .rolling(window=window, min_periods=0)
    )
    if metric == 'sum':
        out_df = group_roll_df.sum()
    elif metric == 'mean':
        out_df = group_roll_df.mean()
    else:
        raise ValueError("'metric' must be one of: 'mean', 'sum'")
    return out_df

def preprocess_merge_df(
        ems_df,
        all_311_df,
        date_start='2010-01-01',
        date_end = '2024-12-31',
        summer_only=False
    ):
    # Get aux data
    weather_df = _weather.download_weather('2010-01-01T00:00:00', '2025-12-31T23:59:59')
    hvi_df = _misc.download_hvi()
    cdtas = _zones.download_community_districts()
    cdta_population = _zones.download_cd_population()

    hvi_df['borough'] = hvi_df['CDTACode'].astype(str).str[:2]
    hvi_df['borough_code'] = hvi_df['borough'].map(CDTA_BOROUGH_LOOKUP)
    hvi_df['cdta'] = hvi_df['borough_code'].astype(str) + hvi_df['CDTACode'].astype(str).str[-2:]

    cdta_population['borough_code'] = cdta_population['borough'].map(CDTA_BOROUGH_LOOKUP)
    cdta_population['cdta'] = cdta_population['borough_code'].astype(str) + cdta_population['cd_number'].str.zfill(2)

    all_311_df = gpd.read_file('./311_calls.gpkg')
    cdtas = cdtas.set_crs('EPSG:4326')
    all_311_df = all_311_df.sjoin(cdtas[['geometry', 'boro_cd']]) 
    # Separate FHE from rest of hydrant data
    all_311_df.loc[(all_311_df['descriptor']=='Fire Hydrant Emergency (FHE)'), 'request_type'] = 'fhe'

    # Prep EMS
    ems_df = ems_df.loc[~ems_df['communitydistrict'].isna()]
    ems_df['communitydistrict'] = ems_df['communitydistrict'].astype(int).astype(str)
    ems_df = ems_df.loc[ems_df['final_call_type'] == 'HEAT']

    date_range = pd.date_range(date_start, date_end)
    date_df = pd.DataFrame({'date':date_range}).set_index('date')

    # Get 311 counts by cdta
    cdta_311_counts = all_311_df.groupby(['boro_cd', 'date', 'request_type']).size()
    cdta_311_counts.name = '311_counts'
    cdta_311_counts = cdta_311_counts.reset_index()
    cdta_311_counts = cdta_311_counts.rename(columns={'boro_cd':'cdta'})
    cdta_311_counts = cdta_311_counts.pivot(index=['cdta','date'], columns='request_type')['311_counts'].fillna(0).reset_index()
    all_dfs = []
    for cdta in cdta_311_counts['cdta'].unique():
        cdta_count = cdta_311_counts.loc[cdta_311_counts['cdta']==cdta].set_index('date').join(date_df, how='right')
        cdta_count['cdta']= cdta
        all_dfs.append(cdta_count)
    cdta_311_counts_filled = pd.concat(all_dfs).fillna(0)

    all_dates = date_range
    all_cdtas = cdtas['boro_cd'].unique()

    # Merge in weather
    full_index = pd.MultiIndex.from_product([all_dates, all_cdtas], names=['date', 'cdta'])
    cdta_311_complete = cdta_311_counts_filled.reset_index().set_index(['date', 'cdta']).reindex(full_index, fill_value=0).reset_index()
    cdta_311_weather = cdta_311_complete.merge(weather_df, left_on='date', right_on='time',how='left')

    # Merge in HVI and population data
    hvi_df = hvi_df.groupby('cdta')[['HVI_RANK','SURFACE_TEMP','MEDIAN_INCOME','GREENSPACE','PCT_HOUSEHOLDS_AC','PCT_BLACK_POP']].mean()
    hvi_df = hvi_df.reset_index().merge(cdta_population[['cdta', '_2010_population']], on='cdta').rename(columns={'_2010_population': 'population'})
    hvi_df['population'] = hvi_df['population'].astype(float)
    cdta_311_hvi_weather = cdta_311_weather.merge(hvi_df, on='cdta', how='inner')

    # Get heat counts by cdta
    ems_df['datetime'] = pd.to_datetime(ems_df['incident_datetime'])
    ems_df['date'] = pd.to_datetime(ems_df['datetime'].dt.date)
    heat_inc_count = (ems_df
                      .groupby(['communitydistrict', 'date'])
                      .size()
                      .rename('heat_ems_count')
                      ).reset_index()

    all_dfs = []
    for cdta in heat_inc_count['communitydistrict'].unique():
        cdta_count = heat_inc_count.loc[heat_inc_count['communitydistrict']==cdta].set_index('date').join(date_df, how='right')
        cdta_count['communitydistrict']= cdta
        all_dfs.append(cdta_count)
    heat_inc_count_filled = pd.concat(all_dfs).fillna(0)
    heat_inc_count_filled = heat_inc_count_filled.rename(columns={'communitydistrict':'cdta'})
    heat_inc_count_filled = heat_inc_count_filled.reset_index().set_index(['cdta','date'])

    # Merge in heat heat ems data
    cdta_alldata = cdta_311_hvi_weather.set_index(['cdta', 'date']).join(heat_inc_count_filled)
    cdta_alldata['population'] = cdta_alldata['population'].astype(float)

    cdta_alldata = cdta_alldata.fillna(0)

    # Apply date filter (optional)
    if summer_only:
        cdta_alldata = cdta_alldata.loc[
            (cdta_alldata.index.get_level_values(1).month <=10) &
            (cdta_alldata.index.get_level_values(1).month >= 6)
        ]

    return cdta_alldata