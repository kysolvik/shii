"""Module to prepare and merge all 311 complaint data into a GeoPackage."""

import pandas as pd
import geopandas as gpd
from shapely import Point
from ._311 import download_311_complaints


def convert_to_gdf(df, lon_col='longitude', lat_col='latitude', crs='EPSG:4326'):
    """Convert a DataFrame with longitude and latitude columns to a GeoDataFrame."""
    geometry = [Point(xy) for xy in zip(df[lon_col], df[lat_col])]
    gdf = gpd.GeoDataFrame(df, geometry=geometry, crs=crs)
    return gdf


def prepare_all_311_complaints(app_token, year_range=range(2010, 2026), output_path='311_calls.gpkg'):
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
        GeoDataFrame containing all merged 311 complaints with geometry and datetime columns.
    """

    complaint_types = ['hydrant', 'ac', 'ventilation', 'power']

    # Dictionary to hold dataframes for each complaint type
    complaint_dfs = {}

    for complaint_type in complaint_types:
        print(f"Downloading {complaint_type} complaints...")
        complaint_list = []
        for y in year_range:
            incidents = download_311_complaints(
                app_token=app_token,
                complaint_type=complaint_type,
                limit=1000000,
                start_timestamp=f"{y}-01-01T00:00:00",
                end_timestamp=f"{y}-12-31T23:59:59"
            )
            print(f"  Year {y}: {incidents.shape[0]} records")
            complaint_list.append(incidents)
        df = pd.concat(complaint_list, ignore_index=True)
        # Convert to GeoDataFrame
        df = convert_to_gdf(df)
        df['complaint_type'] = complaint_type
        complaint_dfs[complaint_type] = df

    # Concatenate all complaint types
    all_complaints_df = pd.concat(list(complaint_dfs.values()), ignore_index=True)

    # Add datetime columns
    all_complaints_df['datetime'] = pd.to_datetime(all_complaints_df['created_date'])
    all_complaints_df['date'] = pd.to_datetime(all_complaints_df['datetime'].dt.date)
    all_complaints_df['doy'] = all_complaints_df['datetime'].dt.dayofyear

    # Save to GeoPackage
    all_complaints_df.to_file(output_path, driver='GPKG')
    print(f"Saved {all_complaints_df.shape[0]} records to {output_path}")

    return all_complaints_df