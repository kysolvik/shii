"""Download and manage miscellanous datasets"""

import pandas as pd


def download_hvi():
    hvi_raw = pd.read_csv('https://a816-dohbesp.nyc.gov/IndicatorPublic/data-features/hvi/hvi-nta-2020.csv')
    return hvi_raw