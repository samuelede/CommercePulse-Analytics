"""Generate campaign recommendations from segments and holiday data."""
import pandas as pd

from python.enrich.holiday_api import get_next_holiday
from python.utils.db import get_logger

logger = get_logger(__name__)

# Segment -> campaign mapping
CAMPAIGN_RULES = {
    "VIP Customer": "Premium Loyalty Campaign",
    "Returning Customer": "Seasonal Discount Campaign",
    "New Customer": "Welcome Offer Campaign",
    "At-Risk Customer": "Win-Back Campaign",
}


_UNSET = object()


def build_campaigns(segmentation, holiday=_UNSET):
    """Return campaign recommendation dataset.

    holiday omitted  -> fetch the next actionable holiday
    holiday=None     -> no holiday found; use a neutral placeholder
    holiday={...}    -> use the one supplied
    """
    if holiday is _UNSET:
        holiday = get_next_holiday()

    if holiday is None:
        logger.warning(
            "No actionable holiday available; using a neutral placeholder so "
            "recommendations still generate"
        )
        holiday = {
            "holiday_name": "No upcoming holiday",
            "days_until_holiday": 0,
        }

    df = segmentation[["customer_id", "segment"]].copy()
    df["holiday_name"] = holiday["holiday_name"]
    df["days_until_holiday"] = holiday["days_until_holiday"]
    df["recommended_campaign"] = df["segment"].map(CAMPAIGN_RULES).fillna(
        "General Engagement Campaign"
    )
    logger.info("Generated %d campaign recommendations", len(df))
    return df