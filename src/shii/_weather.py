"""Download and manage weather data."""


import pandas
import meteostat as ms
from datetime import datetime


def _clean_dates(start_timestamp: str, end_timestamp: str) -> str:
    """Check date validity and return datetime object"""

    if start_timestamp and end_timestamp:
        start_dt = datetime.fromisoformat(start_timestamp)
        end_dt = datetime.fromisoformat(end_timestamp)

        if start_dt >= end_dt:
            raise ValueError("start_timestamp must be before end_timestamp.")
    return start_dt, end_dt


def download_weather(
    start_timestamp: str,
    end_timestamp: str,
    latitude: float = 40.747634,
    longitude: float = -73.990291,
    num_stations: int = 3,
    aggregation: str = 'daily'
) -> pandas.DataFrame:
    """
    Download weather station data from meteostat

    Parameters
    ----------
    start_timestamp : str, required
        Start datetime in ISO string format.
    end_timestamp : str, required
        End datetime in ISO string format.
    latitude : float, optional
        Latitude of point to search for nearby stations. Default is point in Midtown
        Manhattan.
    longitude : float, optional
        Longitude of point to search for nearby stations. Default is point in Midtown
        Manhattan.
    num_stations : int, optional
        Number of nearest stations to download. Default is 3.
    aggregation : str, optional
        Time-period for weather aggregation. If None, daily. Daily is only option right now.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing aggregated weather data

    Notes
    -----
    Currently downloads data for 3 nearest weather stations to Midtown Manhattan:
        KNYC0, NYC/Yorkville
        KJRB0, NY/Wall Street
        72503, LaGuardia Airport
    
    Final result is the interpolation of these 3 stations
    """
    target_point = ms.Point(latitude, longitude, 0) 

    # Check and clean dates
    start_dt, end_dt = _clean_dates(start_timestamp, end_timestamp)

    if aggregation != "daily":
        raise ValueError(f"aggregation={aggregation} is not currently supported. \n"
                         "Currently, only 'daily' (the default) is supported")
    # Get nearby weather stations
    stations = ms.stations.nearby(target_point, limit=num_stations)
    if stations.shape[0] == 0:
        raise ValueError(f"No stations found within 50km of point {latitude}, {longitude}.")

    # Get daily data & perform interpolation
    weather_timeseries = ms.daily(stations, start_dt, end_dt)
    weather_df = ms.interpolate(weather_timeseries, target_point).fetch()

    return weather_df