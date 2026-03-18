"""Module to prepare and merge all 311 request data into a GeoPackage."""

import pandas as pd
import geopandas as gpd
from shapely import Point
from ._311 import download_311_requests


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

    request_types = ['hydrant', 'ac', 'ventilation', 'power']

    # Dictionary to hold dataframes for each request type
    request_dfs = {}

    for request_type in request_types:
        print(f"Downloading {request_type} requests...")
        request_list = []
        for y in year_range:
            incidents = download_311_requests(
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