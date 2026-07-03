"""Classify customers into business segments from order behavior."""
import pandas as pd

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)


def _assign_segment(row, ref_date):
    orders = row["total_orders"]
    spend = row["total_spend"]
    last = row["last_purchase_date"]

    days_since = (
        (ref_date - last).days if pd.notnull(last) else None
    )

    if days_since is not None and days_since > config.CHURN_DAYS_THRESHOLD:
        return "At-Risk Customer"
    if (
        spend >= config.VIP_SPEND_THRESHOLD
        or orders >= config.VIP_ORDER_THRESHOLD
    ):
        return "VIP Customer"
    if orders >= config.RETURNING_ORDER_THRESHOLD:
        return "Returning Customer"
    return "New Customer"


def build_segmentation(customers, orders):
    """Return customer segmentation dataset."""
    paid = orders.copy()
    if "payment_status" in paid.columns:
        paid = paid[paid["payment_status"].str.lower() == "completed"]
        if paid.empty:
            paid = orders.copy()

    agg = (
        paid.groupby("customer_id")
        .agg(
            total_orders=("order_id", "count"),
            total_spend=("amount", "sum"),
            last_purchase_date=("created_at", "max"),
        )
        .reset_index()
    )

    df = customers.merge(agg, on="customer_id", how="left")
    df["total_orders"] = df["total_orders"].fillna(0).astype(int)
    df["total_spend"] = df["total_spend"].fillna(0.0)

    ref_date = pd.Timestamp.now("UTC").tz_localize(None)
    df["segment"] = df.apply(
        lambda r: _assign_segment(r, ref_date), axis=1
    )

    df = df.rename(columns={"name": "customer_name"})
    result = df[
        [
            "customer_id",
            "customer_name",
            "total_orders",
            "total_spend",
            "segment",
        ]
    ].copy()
    logger.info(
        "Segmentation complete: %s",
        result["segment"].value_counts().to_dict(),
    )
    return result
