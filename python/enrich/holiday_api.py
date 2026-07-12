"""Retrieve and normalize holiday data from a public holiday API.

Two behaviours matter for campaign planning and are easy to get wrong:

1. Regional holidays. A UK query returns subdivision-only dates such as the
   Battle of the Boyne (Northern Ireland) or St Andrew's Day (Scotland).
   Anchoring a nationwide campaign to one of those is wrong, so by default
   only nationwide holidays are used.

2. Lead time. A holiday two days away is useless to a marketing team; they
   cannot brief, build, and ship a campaign in that window. The pipeline
   therefore selects the nearest holiday at least HOLIDAY_MIN_LEAD_DAYS out,
   which is what makes the recommendation actionable rather than merely
   accurate.

Calendarific is used when an API key is present; the keyless Nager.Date API
is the fallback.
"""
import datetime

import pandas as pd
import requests

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

TIMEOUT = 30


def _fetch_calendarific(year):
    """Fetch one year from Calendarific. Rows carry a nationwide flag."""
    params = {
        "api_key": config.HOLIDAY_API_KEY,
        "country": config.HOLIDAY_COUNTRY,
        "year": year,
    }
    resp = requests.get(
        f"{config.HOLIDAY_API_BASE}/holidays", params=params, timeout=TIMEOUT
    )
    resp.raise_for_status()
    holidays = resp.json().get("response", {}).get("holidays", [])

    rows = []
    for h in holidays:
        # Calendarific marks regional dates via states: "All" (or the string
        # "All") means nationwide; a list means subdivision-specific.
        states = h.get("states")
        nationwide = states in (None, "All") or (
            isinstance(states, str) and states.lower() == "all"
        )
        rows.append(
            {
                "holiday_name": h.get("name"),
                "holiday_date": h.get("date", {}).get("iso", "")[:10],
                "nationwide": bool(nationwide),
            }
        )
    return rows


def _fetch_nager(year):
    """Fetch one year from Nager.Date (keyless). Rows carry a nationwide flag."""
    url = (
        f"https://date.nager.at/api/v3/PublicHolidays/"
        f"{year}/{config.HOLIDAY_COUNTRY}"
    )
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()

    rows = []
    for h in resp.json():
        # Nager: `counties` is null for nationwide holidays and a list of
        # subdivision codes (e.g. ["GB-NIR"]) for regional ones. `global` says
        # the same thing; both are checked because the API has varied.
        counties = h.get("counties")
        is_global = h.get("global")
        nationwide = (not counties) and (is_global is not False)
        rows.append(
            {
                "holiday_name": h.get("name"),
                "holiday_date": h.get("date"),
                "nationwide": bool(nationwide),
            }
        )
    return rows


def _fetch_all(year):
    """Fetch one year of holidays from whichever API is configured."""
    try:
        return (
            _fetch_calendarific(year)
            if config.HOLIDAY_API_KEY
            else _fetch_nager(year)
        )
    except requests.RequestException as exc:
        logger.warning("Holiday API failed (%s); using Nager fallback", exc)
        return _fetch_nager(year)


def get_holidays(nationwide_only=None, min_lead_days=None):
    """Return upcoming holidays as a normalized DataFrame.

    Columns: holiday_name, holiday_date, nationwide, days_until_holiday.
    Sorted soonest first. Filters are applied before the return.

    Fetches the following year as well, so that a run late in December still
    finds an actionable holiday rather than falling off the end of the year.
    """
    if nationwide_only is None:
        nationwide_only = config.HOLIDAY_NATIONWIDE_ONLY
    if min_lead_days is None:
        min_lead_days = config.HOLIDAY_MIN_LEAD_DAYS

    year = int(config.HOLIDAY_YEAR)
    rows = _fetch_all(year) + _fetch_all(year + 1)

    df = pd.DataFrame(rows)
    if df.empty:
        logger.warning("Holiday API returned no records")
        return df

    df["holiday_date"] = pd.to_datetime(df["holiday_date"], errors="coerce")
    df = df.dropna(subset=["holiday_date"])
    df = df.drop_duplicates(subset=["holiday_name", "holiday_date"])

    today = pd.Timestamp(datetime.date.today())
    df["days_until_holiday"] = (df["holiday_date"] - today).dt.days
    total = len(df)

    if nationwide_only:
        regional = df[~df["nationwide"]]
        if not regional.empty:
            names = sorted(set(regional["holiday_name"]))
            logger.info(
                "Excluding %d regional holiday(s): %s",
                len(regional),
                ", ".join(names[:5]),
            )
        df = df[df["nationwide"]]

    df = df[df["days_until_holiday"] >= min_lead_days]
    df = df.sort_values("holiday_date").reset_index(drop=True)

    logger.info(
        "Retrieved %d holiday(s) of %d, at least %d days out%s",
        len(df),
        total,
        min_lead_days,
        ", nationwide only" if nationwide_only else "",
    )
    return df


def get_next_holiday(nationwide_only=None, min_lead_days=None):
    """Return the nearest actionable upcoming holiday, or None.

    "Actionable" means far enough out to plan a campaign around, and (by
    default) nationwide rather than region-specific.
    """
    df = get_holidays(nationwide_only, min_lead_days)
    if df.empty:
        logger.warning(
            "No holiday found at least %s days out; campaigns will fall back "
            "to a generic placeholder",
            config.HOLIDAY_MIN_LEAD_DAYS if min_lead_days is None else min_lead_days,
        )
        return None

    row = df.iloc[0]
    holiday = {
        "holiday_name": row["holiday_name"],
        "holiday_date": row["holiday_date"],
        "days_until_holiday": int(row["days_until_holiday"]),
    }
    logger.info(
        "Selected holiday: %s (%d days out)",
        holiday["holiday_name"],
        holiday["days_until_holiday"],
    )
    return holiday


if __name__ == "__main__":
    print(get_holidays().to_string(index=False))