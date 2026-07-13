"""CommercePulse end-to-end pipeline entrypoint.

Run standalone with:  python -m python.pipeline
"""
import argparse

from python.enrich.campaigns import build_campaigns
from python.enrich.holiday_api import get_next_holiday
from python.extract.extract_staging import extract_all
from python.load.load_analytics import (
    load_campaigns,
    load_customer_360,
    load_segmentation,
)
from python.load.monday_crm import sync_campaigns
from python.transform.customer_360 import build_customer_360
from python.transform.segmentation import build_segmentation
from python.transform.validation import (
    validate_campaigns,
    validate_customer_360,
    validate_segmentation,
)
from python.utils.db import get_logger

logger = get_logger("pipeline")


def run(skip_crm=False):
    logger.info("=== CommercePulse pipeline start ===")

    data = extract_all()
    customers, products, orders = (
        data["customers"],
        data["products"],
        data["orders"],
    )

    segmentation = build_segmentation(customers, orders)
    validate_segmentation(segmentation)
    load_segmentation(segmentation)

    c360 = build_customer_360(customers, products, orders)
    validate_customer_360(c360)
    load_customer_360(c360)

    holiday = get_next_holiday()
    campaigns = build_campaigns(segmentation, holiday, c360)
    validate_campaigns(campaigns)
    load_campaigns(campaigns)

    if skip_crm:
        logger.info("Skipping Monday CRM sync (--skip-crm)")
    else:
        sync_campaigns(campaigns, c360, segmentation)

    logger.info("=== CommercePulse pipeline complete ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CommercePulse pipeline")
    parser.add_argument(
        "--skip-crm",
        action="store_true",
        help="Run analytics without pushing to Monday CRM",
    )
    args = parser.parse_args()
    run(skip_crm=args.skip_crm)