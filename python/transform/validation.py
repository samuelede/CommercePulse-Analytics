"""Validation checks for analytical outputs before and after load."""
from python.utils.db import get_logger

logger = get_logger(__name__)

VALID_SEGMENTS = {
    "New Customer",
    "Returning Customer",
    "VIP Customer",
    "At-Risk Customer",
}


class ValidationError(Exception):
    pass


def validate_segmentation(df):
    if df.empty:
        raise ValidationError("Segmentation dataset is empty")
    if df["customer_id"].duplicated().any():
        raise ValidationError("Duplicate customer_id in segmentation")
    bad = set(df["segment"].unique()) - VALID_SEGMENTS
    if bad:
        raise ValidationError(f"Unexpected segments: {bad}")
    if (df["total_spend"] < 0).any():
        raise ValidationError("Negative total_spend detected")
    logger.info("Segmentation validation passed")


def validate_customer_360(df):
    if df.empty:
        raise ValidationError("Customer 360 dataset is empty")
    if df["customer_id"].duplicated().any():
        raise ValidationError("Duplicate customer_id in Customer 360")
    if (df["lifetime_value"] < 0).any():
        raise ValidationError("Negative lifetime_value detected")
    if (df["total_orders"] < 0).any():
        raise ValidationError("Negative total_orders detected")
    if (df["purchase_frequency"] < 0).any():
        raise ValidationError("Negative purchase_frequency detected")
    if df["churn_risk"].isnull().any():
        raise ValidationError("Null churn_risk values")
    if not set(df["churn_risk"].unique()) <= {"Low", "Medium", "High"}:
        raise ValidationError("Unexpected churn_risk values")
    # A customer with no orders must have a zero rate, not a phantom one.
    no_orders = df[df["total_orders"] == 0]
    if not no_orders.empty and (no_orders["purchase_frequency"] > 0).any():
        raise ValidationError("purchase_frequency > 0 for a customer with no orders")
    logger.info("Customer 360 validation passed")


def validate_campaigns(df):
    if df.empty:
        raise ValidationError("Campaign dataset is empty")
    if df["customer_id"].duplicated().any():
        raise ValidationError("Duplicate customer_id in campaigns")
    if df["recommended_campaign"].isnull().any():
        raise ValidationError("Null recommended_campaign values")
    if df["priority"].isnull().any():
        raise ValidationError("Null priority values")
    if not df["priority"].between(1, 4).all():
        raise ValidationError("priority outside the expected 1-4 range")
    # An urgent campaign must never be handed to a healthy, low-risk customer:
    # that would mean the churn signal is not reaching the rule engine.
    urgent_low_risk = df[(df["priority"] == 1) & (df["churn_risk"] == "Low")]
    if not urgent_low_risk.empty:
        raise ValidationError(
            "Priority 1 assigned to Low churn_risk customers; "
            "Customer 360 signal is not reaching the campaign rules"
        )
    logger.info("Campaign validation passed")