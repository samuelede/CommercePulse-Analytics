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
    if (df["lifetime_value"] < 0).any():
        raise ValidationError("Negative lifetime_value detected")
    if df["churn_risk"].isnull().any():
        raise ValidationError("Null churn_risk values")
    logger.info("Customer 360 validation passed")


def validate_campaigns(df):
    if df.empty:
        raise ValidationError("Campaign dataset is empty")
    if df["recommended_campaign"].isnull().any():
        raise ValidationError("Null recommended_campaign values")
    logger.info("Campaign validation passed")
