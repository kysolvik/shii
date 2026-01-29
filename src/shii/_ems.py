"""Download and manage EMS records from NYC Open Data."""


import sodapy
import pandas
from datetime import datetime
import os

def download_heat_incidents(
    app_token: str = None,
    limit: int = None,
    start_timestamp: str = None,
    end_timestamp: str = None,
) -> pandas.DataFrame:
    """
    Download EMS incident dispatch data from NYC Open Data for heat strokes only.

    Parameters
    ----------
    app_token : str, optional
        Socrata API token for authentication. If None, requests are limited to 1000
        records and may be rate-limited.
    limit : int, optional
        Maximum number of records to download. If None, downloads all available records.
    start_timestamp : str, optional
        Filter incidents on or after this timestamp. If None, no lower bound is applied.
    end_timestamp : str, optional
        Filter incidents before this timestamp. If None, no upper bound is applied.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing EMS incident dispatch records filtered for heat strokes.

    Notes
    -----
    The function queries the NYC EMS Incident Dispatch Data dataset using the
    sodapy library. It filters for incidents where the chief complaint contains
    "heat stroke" (case-insensitive).

    The dataset ID is "76xm-jjuj" from the NYC Open Data portal.
    The incident_datetime field is used for date filtering and is stored as a
    floating timestamp (seconds since epoch) in the Socrata API.
    """
    # Initialize connection to NYC Open Data Socrata API
    client = sodapy.Socrata(
        "data.cityofnewyork.us",
        app_token,
    )

    # Build where clause for heat stroke incidents
    where_clause = "(initial_call_type = 'HEAT' OR final_call_type = 'HEAT')"
    
    # Add date filters if provided
    if start_timestamp:
        where_clause += f" AND incident_datetime >= '{start_timestamp}'"
    
    if end_timestamp:
        where_clause += f" AND incident_datetime < '{end_timestamp}'"

    try:
        # Fetch data with optional limit
        if limit:
            results = client.get(
                "76xm-jjuj",
                where=where_clause,
                limit=limit,
            )
        else:
            results = client.get(
                "76xm-jjuj",
                where=where_clause,
            )

        # Convert to DataFrame
        df = pandas.DataFrame.from_records(results)

        return df

    except Exception as e:
        raise RuntimeError(f"Failed to download EMS heat stroke data: {e}") from e
    finally:
        client.close()


if __name__ == "__main__":
    df_heat_incidents = download_heat_incidents(
        app_token=os.getenv("NYCOD_APP_TOKEN"),
        limit=1000,
        start_date=datetime(2020, 6, 1),
        end_date=datetime(2020, 8, 31),
    )
    print(df_heat_incidents.head())