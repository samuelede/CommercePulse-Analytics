"""Build the unified Customer 360 dataset."""
import pandas as pd

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

DAYS_PER_MONTH = 30.44  # mean Gregorian month


def _completed(orders):
    """Restrict to completed orders, falling back if the filter empties them."""
    if "payment_status" not in orders.columns:
        return orders
    done = orders[orders["payment_status"].str.lower() == "completed"]
    return done if not done.empty else orders


def build_customer_360(customers, products, orders):
    """Return Customer 360 dataset with value, activity, and engagement metrics.

    total_orders       raw count of completed orders
    purchase_frequency orders per month across the customer's active lifespan,
                       measured from first purchase to today. This is a rate,
                       not a count: it separates "5 orders over 3 years" from
                       "5 orders in 3 weeks", which a bare count cannot.
    """
    paid = _completed(orders)

    agg = (
        paid.groupby("customer_id")
        .agg(
            lifetime_value=("amount", "sum"),
            total_orders=("order_id", "count"),
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
    df["total_orders"] = df["total_orders"].fillna(0).astype(int)
    df["preferred_category"] = df["preferred_category"].fillna("None")

    ref_date = pd.Timestamp.now("UTC").tz_localize(None)

    # Active lifespan in months, floored at one month so a customer who bought
    # once today does not divide by ~zero and report an absurd rate.
    tenure_days = (ref_date - df["first_purchase_date"]).dt.days
    tenure_months = (tenure_days / DAYS_PER_MONTH).clip(lower=1.0)
    df["purchase_frequency"] = (
        (df["total_orders"] / tenure_months).fillna(0.0).round(2)
    )

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
            "total_orders",
            "purchase_frequency",
            "last_purchase_date",
            "preferred_category",
            "churn_risk",
        ]
    ].copy()
    logger.info("Customer 360 built for %d customers", len(result))
    return result