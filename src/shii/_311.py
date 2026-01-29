
"""Download and manage 311 records from NYC Open Data."""


import sodapy
import pandas
from datetime import datetime
import os

def _build_hydrant_where_clause() -> str:
    """Build hydrant complaint where clause for query."""

    problem_detail_filter = [
        'Illegal Use of Fire Hydrant (CIN)',
        'Hydrant Running (WC3)',
        'Hydrant Running Full (WA4)',
        'Request to Open A Hydrant (WC4)',
        'Hydrant Locking Device Request (Use Comments) (WC5)'
    ]
    # Build where clause for Fire Hydrant issues
    where_clause = f"(descriptor in{tuple(problem_detail_filter)})"

    return where_clause

def _build_ac_where_clause() -> str:
    """Build AC complaint where clause for query."""

    # Build where clause for Fire Hydrant issues
    where_clause = f"(descriptor = 'Air Conditioning Problem')"

    return where_clause

def _build_ventilation_where_clause() -> str:
    """Build ventilation complaint where clause for query."""

    # Build where clause for Fire Hydrant issues
    where_clause = f"(starts_with(lower(descriptor), 'ventilation'))"

    return where_clause

def _build_power_where_clause() -> str:
    """Build power complaint where clause for query."""

    # Build where clause for Fire Hydrant issues
    where_clause = f"(lower(descriptor) = 'power outage')"

    return where_clause

def download_311_complaints(
    complaint_type: str = None,
    app_token: str = None,
    limit: int = None,
    start_timestamp: str = None,
    end_timestamp: str = None,
    where_clause: str = None,
) -> pandas.DataFrame:
    """
    Download 311 complaints from NYC Open Data based on a custom where clause.

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
    complaint_type : str, optional
        Filter complaints by complaint type. If None, no complaint type filter is applied.
    where_clause : str
        Custom SQL-like where clause to filter records.

    Returns
    -------
    pandas.DataFrame
        DataFrame containing 311 complaints for the specified complaint type or where_clause.

    Notes
    -----
    The function queries the NYC 311 Complaints dataset using the
    sodapy library.

    The dataset ID is "erm2-nwe9" from the NYC Open Data portal.
    The incident_datetime field is used for date filtering and is stored as a
    floating timestamp (seconds since epoch) in the Socrata API.
    """
    # Initialize connection to NYC Open Data Socrata API
    client = sodapy.Socrata(
        "data.cityofnewyork.us",
        app_token,
    )

    if complaint_type:
        # Look up complaint where_clause
        # Could probably convert to dict lookup if more types are added
        if complaint_type == 'hydrant':
            where_clause = _build_hydrant_where_clause()
        elif complaint_type == 'ac':
            where_clause = _build_ac_where_clause()
        elif complaint_type == 'ventilation':
            where_clause = _build_ventilation_where_clause()
        elif complaint_type == 'power':
            where_clause = _build_power_where_clause()
        else:
            raise ValueError(f"Unsupported complaint_type: {complaint_type}\n"
                             " Supported types are 'hydrant', 'ac', 'power', or 'ventilation'."
                             " Alternatively, use where_clause parameter for custom filtering.")
    elif where_clause is None:
        # Default where clause
        where_clause = ""

    # Add date filters if provided
    if start_timestamp:
        where_clause += f" AND created_date >= '{start_timestamp}'"
    
    if end_timestamp:
        where_clause += f" AND created_date < '{end_timestamp}'"

    try:
        # Fetch data with optional limit
        if limit:
            results = client.get(
                "erm2-nwe9",
                where=where_clause,
                limit=limit,
            )
        else:
            results = client.get(
                "erm2-nwe9",
                where=where_clause,
            )

        # Convert to DataFrame
        df = pandas.DataFrame.from_records(results)

        return df

    except Exception as e:
        raise RuntimeError(f"Failed to download 311 complaints data: {e}") from e
    finally:
        client.close()