"""Build the unified Customer 360 dataset."""
import pandas as pd

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)


def build_customer_360(customers, products, orders):
    """Return Customer 360 dataset with value and engagement metrics."""
    paid = orders.copy()
    if "payment_status" in paid.columns:
        completed = paid[paid["payment_status"].str.lower() == "completed"]
        if not completed.empty:
            paid = completed

    # Lifetime value, frequency, recency
    agg = (
        paid.groupby("customer_id")
        .agg(
            lifetime_value=("amount", "sum"),
            purchase_frequency=("order_id", "count"),
            last_purchase_date=("created_at", "max"),
            first_purchase_date=("created_at", "min"),
        )
        .reset_index()
    )

    # Preferred category via product join
    prod_cat = products[["product_id", "category"]]
    joined = paid.merge(prod_cat, on="product_id", how="left")
    pref = (
        joined.groupby(["customer_id", "category"])
        .size()
        .reset_index(name="cnt")
        .sort_values(["customer_id", "cnt"], ascending=[True, False])
        .drop_duplicates("customer_id")
        .rename(columns={"category": "preferred_category"})
    )[["customer_id", "preferred_category"]]

    df = customers[["customer_id"]].merge(agg, on="customer_id", how="left")
    df = df.merge(pref, on="customer_id", how="left")

    df["lifetime_value"] = df["lifetime_value"].fillna(0.0)
    df["purchase_frequency"] = df["purchase_frequency"].fillna(0).astype(int)
    df["preferred_category"] = df["preferred_category"].fillna("None")

    ref_date = pd.Timestamp.now("UTC").tz_localize(None)
    days_since = (ref_date - df["last_purchase_date"]).dt.days
    df["churn_risk"] = days_since.apply(
        lambda d: "High"
        if pd.isnull(d) or d > config.CHURN_DAYS_THRESHOLD
        else ("Medium" if d > config.CHURN_DAYS_THRESHOLD / 2 else "Low")
    )

    result = df[
        [
            "customer_id",
            "lifetime_value",
            "purchase_frequency",
            "last_purchase_date",
            "preferred_category",
            "churn_risk",
        ]
    ].copy()
    logger.info("Customer 360 built for %d customers", len(result))
    return result
