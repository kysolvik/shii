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
    aggregation: str = 'daily'
) -> pandas.DataFrame:
    """
    Download weather station data from meteostat

    Parameters
    ----------
    start_timestamp : str, optional
        Start datetime in ISO string format
    end_timestamp : str, optional
        End datetime in ISO string format
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
    # Near Midtown Manhattan
    target_point = ms.Point(40.747634, -73.990291, 0) 

    # Check and clean dates
    start_dt, end_dt = _clean_dates(start_timestamp, end_timestamp)

    if aggregation != "daily":
        raise ValueError(f"aggregation={aggregation} is not currently supported. \n"
                         "Currently, only 'daily' (the default) is supported")
    # Get nearby weather stations
    stations = ms.stations.nearby(target_point, radius = 10000)
    if stations.shape[0] != 3:
        raise ValueError(f"Got {stations.shape[0]} stations, expected 3")

    # Get daily data & perform interpolation
    weather_timeseries = ms.daily(stations, start_dt, end_dt)
    weather_df = ms.interpolate(weather_timeseries, target_point).fetch()

    return weather_df