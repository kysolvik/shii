"""Download spatial data for neighborhood tabulation areas, zipcodes, etc."""

import sodapy
import geopandas
import pandas

def _init_client(
        app_token: str = None
        ) -> sodapy.Socrata:
    
    return sodapy.Socrata(
        "data.cityofnewyork.us",
        app_token,
        timeout=600
    )

def _download_helper(
    dataset_id: str = None,
    app_token: str = None
    ) -> geopandas.GeoDataFrame:
    """Helper for initializing client and downloading"""
    # Initialize connection to NYC Open Data Socrata API
    client = _init_client(app_token)
    # Get dataset by id as geojson
    results = client.get(dataset_identifier=dataset_id,
                         content_type='geojson')
    # Convert to GeoDataFrame and return
    return geopandas.GeoDataFrame.from_features(results)

def download_zipcodes(
        app_token: str = None
    ) -> geopandas.GeoDataFrame:
    """
    Download Modified Zipcode Tabulation Areas
    https://data.cityofnewyork.us/Health/Modified-Zip-Code-Tabulation-Areas-MODZCTA-Map/5fzm-kpwv

    Parameters
    ----------
    app_token : str, optional
        Socrata API token for authentication. If None, requests are limited to 1000
        records and may be rate-limited.

    Returns
    -------
    geopandas.GeoDataFrame
        DataFrame containing Modified Zipcode Tabulation Areas
    """
    return _download_helper('pri4-ifjk', app_token)

def download_cd_population(
        app_token: str = None
    ) -> pandas.DataFrame:
    """
    https://data.cityofnewyork.us/City-Government/New-York-City-Population-By-Community-Districts/xi7c-iiu2/about_data
    """
    client = _init_client(app_token)
    pop_records = client.get(dataset_identifier='xi7c-iiu2')
    return pandas.DataFrame.from_records(pop_records)

def download_community_districts(
        app_token: str = None
    ) -> geopandas.GeoDataFrame:
    """
    https://data.cityofnewyork.us/City-Government/Community-Districts/5crt-au7u/about_data
    """
    return _download_helper('5crt-au7u', app_token)

def download_census_tracts(
        app_token: str = None
    ) -> geopandas.GeoDataFrame:
    """
    https://data.cityofnewyork.us/City-Government/2020-Census-Tracts-Mapped/weqx-t5xr
    """
    return _download_helper('63ge-mke6', app_token)

def download_neighborhoods(
        app_token: str = None
    ) -> geopandas.GeoDataFrame:
    """
    https://data.cityofnewyork.us/City-Government/2020-Neighborhood-Tabulation-Areas-NTAs-/9nt8-h7nd/about_data
    """
    return _download_helper('9nt8-h7nd', app_token)