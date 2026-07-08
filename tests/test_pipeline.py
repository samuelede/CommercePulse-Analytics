"""Unit tests for segmentation, customer 360, and campaign logic."""
import pandas as pd

from python.enrich.campaigns import build_campaigns
from python.transform.customer_360 import build_customer_360
from python.transform.segmentation import build_segmentation
from python.transform.validation import (
    validate_campaigns,
    validate_customer_360,
    validate_segmentation,
)


def _fixtures():
    customers = pd.DataFrame(
        {
            "customer_id": ["C1", "C2", "C3"],
            "name": ["Alpha", "Beta", "Gamma"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": ["P1", "P2"],
            "category": ["Electronics", "Home"],
        }
    )
    orders = pd.DataFrame(
        {
            "order_id": ["O1", "O2", "O3", "O4"],
            "customer_id": ["C1", "C1", "C1", "C2"],
            "product_id": ["P1", "P1", "P2", "P2"],
            "amount": [6000, 100, 200, 50],
            "payment_status": ["completed"] * 4,
            "created_at": pd.to_datetime(
                ["2026-06-01", "2026-06-10", "2026-06-20", "2026-06-15"]
            ),
        }
    )
    return customers, products, orders


def test_segmentation():
    customers, _, orders = _fixtures()
    seg = build_segmentation(customers, orders)
    validate_segmentation(seg)
    assert seg.loc[seg.customer_id == "C1", "segment"].iloc[0] == "VIP Customer"
    assert len(seg) == 3


def test_customer_360():
    customers, products, orders = _fixtures()
    c360 = build_customer_360(customers, products, orders)
    validate_customer_360(c360)
    assert c360.loc[c360.customer_id == "C1", "lifetime_value"].iloc[0] == 6300
    assert (
        c360.loc[c360.customer_id == "C1", "preferred_category"].iloc[0]
        == "Electronics"
    )


def test_campaigns():
    customers, _, orders = _fixtures()
    seg = build_segmentation(customers, orders)
    holiday = {"holiday_name": "Christmas", "days_until_holiday": 30}
    camp = build_campaigns(seg, holiday)
    validate_campaigns(camp)
    vip = camp.loc[camp.customer_id == "C1", "recommended_campaign"].iloc[0]
    assert vip == "Premium Loyalty Campaign"
