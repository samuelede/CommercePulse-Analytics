"""Generate campaign recommendations from segments, Customer 360, and holidays.

Segment alone is too blunt to drive engagement. Two VIPs are not the same
proposition if one bought last week and the other has been silent for four
months; the second is the one you are about to lose. The rule engine therefore
combines three inputs:

    segment          what kind of customer they are
    churn_risk       whether they are slipping away  (Customer 360)
    lifetime_value   how much that would cost you    (Customer 360)
    holiday          the hook to reach out on        (Holiday API)

The segment x churn_risk matrix is the primary rule; lifetime value acts as a
tiebreaker that can promote a customer to a higher-touch campaign. Every
recommendation carries a priority so the CRM can be sorted by urgency rather
than by customer id.
"""
import pandas as pd

from python.enrich.holiday_api import get_next_holiday
from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

_UNSET = object()

# (segment, churn_risk) -> (campaign, priority)
# Priority: 1 = act now, 4 = routine.
CAMPAIGN_MATRIX = {
    # A lapsing high-value customer is the most urgent case in the book.
    ("VIP Customer", "High"): ("Premium Win-Back Campaign", 1),
    ("VIP Customer", "Medium"): ("Premium Retention Campaign", 2),
    ("VIP Customer", "Low"): ("Premium Loyalty Campaign", 3),

    ("Returning Customer", "High"): ("Win-Back Campaign", 1),
    ("Returning Customer", "Medium"): ("Re-engagement Campaign", 2),
    ("Returning Customer", "Low"): ("Seasonal Discount Campaign", 3),

    # A new customer already at high churn never really landed.
    ("New Customer", "High"): ("Onboarding Rescue Campaign", 2),
    ("New Customer", "Medium"): ("Second Purchase Nudge", 3),
    ("New Customer", "Low"): ("Welcome Offer Campaign", 4),

    ("At-Risk Customer", "High"): ("Win-Back Campaign", 1),
    ("At-Risk Customer", "Medium"): ("Win-Back Campaign", 2),
    ("At-Risk Customer", "Low"): ("Re-engagement Campaign", 3),
}

FALLBACK_CAMPAIGN = ("General Engagement Campaign", 4)

# A Returning customer spending like a VIP is worth treating like one before a
# competitor does. Expressed as a fraction of the VIP threshold so the two
# cannot drift apart.
VIP_UPGRADE_RATIO = 0.6

PLACEHOLDER_HOLIDAY = {
    "holiday_name": "No upcoming holiday",
    "days_until_holiday": 0,
}


def _base_rule(segment, churn_risk):
    return CAMPAIGN_MATRIX.get((segment, churn_risk), FALLBACK_CAMPAIGN)


def _apply_ltv_tiebreak(segment, churn_risk, lifetime_value, campaign, priority):
    """Let lifetime value override rules that segment alone gets wrong.

    Segmentation classifies a lapsed customer as At-Risk regardless of their
    worth, so a customer who spent 14,400 and a customer who spent 90 land in
    the same bucket and receive the same generic win-back. That is the blind
    spot Customer 360 exists to close: a high-value customer walking away is a
    different problem, and a different conversation, from a trivial one.
    """
    upgrade_floor = config.VIP_SPEND_THRESHOLD * VIP_UPGRADE_RATIO

    # A lapsed customer of real value is a premium win-back, not a generic one,
    # even though segmentation has labelled them plain At-Risk.
    if (
        lifetime_value >= config.VIP_SPEND_THRESHOLD
        and churn_risk in ("High", "Medium")
        and segment in ("At-Risk Customer", "Returning Customer")
    ):
        return "Premium Win-Back Campaign", 1

    # A Returning customer spending near the VIP threshold is behaving like a
    # VIP. Recognising that is the difference between growing the account and
    # letting a competitor grow it.
    if (
        segment == "Returning Customer"
        and lifetime_value >= upgrade_floor
        and churn_risk == "Low"
    ):
        return "VIP Upgrade Offer", 2

    return campaign, priority


def build_campaigns(segmentation, holiday=_UNSET, customer_360=None):
    """Return the campaign recommendation dataset.

    segmentation  customer_id, segment (and customer_name)
    customer_360  optional; supplies churn_risk and lifetime_value. Without it
                  the engine degrades to segment-only rules, which is weaker
                  but still valid.
    holiday       omitted -> fetch; None -> none available; dict -> use it
    """
    if holiday is _UNSET:
        holiday = get_next_holiday()

    if holiday is None:
        logger.warning(
            "No actionable holiday available; recommendations will still "
            "generate against a neutral placeholder"
        )
        holiday = PLACEHOLDER_HOLIDAY

    df = segmentation[["customer_id", "segment"]].copy()

    if customer_360 is not None:
        c360 = customer_360[
            ["customer_id", "churn_risk", "lifetime_value"]
        ].copy()
        df = df.merge(c360, on="customer_id", how="left")
    else:
        logger.warning(
            "Customer 360 not supplied; falling back to segment-only rules"
        )
        df["churn_risk"] = "Low"
        df["lifetime_value"] = 0.0

    df["churn_risk"] = df["churn_risk"].fillna("Low")
    df["lifetime_value"] = df["lifetime_value"].fillna(0.0)

    campaigns, priorities = [], []
    for _, row in df.iterrows():
        campaign, priority = _base_rule(row["segment"], row["churn_risk"])
        campaign, priority = _apply_ltv_tiebreak(
            row["segment"],
            row["churn_risk"],
            row["lifetime_value"],
            campaign,
            priority,
        )
        campaigns.append(campaign)
        priorities.append(priority)

    df["recommended_campaign"] = campaigns
    df["priority"] = priorities
    df["holiday_name"] = holiday["holiday_name"]
    df["days_until_holiday"] = holiday["days_until_holiday"]

    result = df[
        [
            "customer_id",
            "segment",
            "churn_risk",
            "lifetime_value",
            "holiday_name",
            "days_until_holiday",
            "recommended_campaign",
            "priority",
        ]
    ].sort_values(["priority", "lifetime_value"], ascending=[True, False])
    result = result.reset_index(drop=True)

    logger.info(
        "Generated %d campaign recommendations: %s",
        len(result),
        result["recommended_campaign"].value_counts().to_dict(),
    )
    return result