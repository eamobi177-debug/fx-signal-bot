"""
Wrapper around the Twelve Data API for fetching forex candle data.
"""
import os
import requests

TWELVE_DATA_API_KEY = os.environ.get("TWELVE_DATA_API_KEY")
BASE_URL = "https://api.twelvedata.com/time_series"

TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
}

PAIRS = ["GBP/USD", "EUR/USD", "AUD/USD", "USD/JPY", "USD/CAD"]


def fetch_closes(symbol: str, timeframe: str, outputsize: int = 100):
    """
    Fetch recent candles for a symbol/timeframe.
    Returns a list of closing prices, oldest first, or None on error.
    """
    interval = TIMEFRAME_MAP.get(timeframe, "1min")
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        resp = requests.get(BASE_URL, params=params, timeout=10)
        data = resp.json()
    except Exception as e:
        return None, f"Request failed: {e}"

    if "values" not in data:
        msg = data.get("message", "Unknown error from Twelve Data")
        return None, msg

    values = list(reversed(data["values"]))
    closes = [float(v["close"]) for v in values]
    return closes, None
