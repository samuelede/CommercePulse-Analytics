"""Retrieve and normalize holiday data from a public holiday API.

Default implementation targets Calendarific (free tier). The Nager.Date
API is supported as a keyless fallback when no API key is supplied.
"""
import datetime

import pandas as pd
import requests

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

TIMEOUT = 30


def _fetch_calendarific():
    params = {
        "api_key": config.HOLIDAY_API_KEY,
        "country": config.HOLIDAY_COUNTRY,
        "year": config.HOLIDAY_YEAR,
    }
    url = f"{config.HOLIDAY_API_BASE}/holidays"
    resp = requests.get(url, params=params, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    holidays = payload.get("response", {}).get("holidays", [])
    rows = []
    for h in holidays:
        rows.append(
            {
                "holiday_name": h.get("name"),
                "holiday_date": h.get("date", {}).get("iso", "")[:10],
            }
        )
    return rows


def _fetch_nager():
    # Keyless fallback: https://date.nager.at
    url = (
        f"https://date.nager.at/api/v3/PublicHolidays/"
        f"{config.HOLIDAY_YEAR}/{config.HOLIDAY_COUNTRY}"
    )
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    rows = []
    for h in resp.json():
        rows.append(
            {"holiday_name": h.get("name"), "holiday_date": h.get("date")}
        )
    return rows


def get_holidays():
    """Return a normalized DataFrame of upcoming holidays."""
    try:
        rows = _fetch_calendarific() if config.HOLIDAY_API_KEY else _fetch_nager()
    except requests.RequestException as exc:
        logger.warning("Holiday API failed (%s); using Nager fallback", exc)
        rows = _fetch_nager()

    df = pd.DataFrame(rows)
    df["holiday_date"] = pd.to_datetime(df["holiday_date"], errors="coerce")
    df = df.dropna(subset=["holiday_date"]).drop_duplicates("holiday_name")

    today = pd.Timestamp(datetime.date.today())
    df = df[df["holiday_date"] >= today]
    df["days_until_holiday"] = (df["holiday_date"] - today).dt.days
    df = df.sort_values("holiday_date").reset_index(drop=True)
    logger.info("Retrieved %d upcoming holidays", len(df))
    return df


def get_next_holiday():
    """Return the single nearest upcoming holiday as a dict, or None."""
    df = get_holidays()
    if df.empty:
        return None
    row = df.iloc[0]
    return {
        "holiday_name": row["holiday_name"],
        "holiday_date": row["holiday_date"],
        "days_until_holiday": int(row["days_until_holiday"]),
    }


if __name__ == "__main__":
    print(get_holidays().head(10).to_string())
