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


def test_value_for_column_types():
    """Monday requires type-specific value shapes; numbers must be strings."""
    from python.load.monday_crm import value_for_column

    assert value_for_column("status", "VIP Customer") == {"label": "VIP Customer"}
    assert value_for_column("numbers", 2600.0) == "2600.0"
    assert value_for_column("numbers", 30) == "30"
    assert value_for_column("text", "Christmas") == "Christmas"
    assert value_for_column("date", "2026-12-25") == {"date": "2026-12-25"}

    # Missing values must not blow up the payload
    assert value_for_column("numbers", None) == "0"
    assert value_for_column("text", None) == ""
    assert value_for_column("numbers", float("nan")) == "0"


def test_column_plan_covers_payload():
    """Every field the sync builds must have a column planned for it."""
    from python.load.monday_crm import COLUMN_PLAN

    required = {
        "customer_id",
        "segment",
        "recommended_campaign",
        "holiday_name",
        "days_until_holiday",
        "churn_risk",
        "lifetime_value",
    }
    assert required == set(COLUMN_PLAN)
    # Status columns must be the two categorical fields
    status_fields = {f for f, (_, t) in COLUMN_PLAN.items() if t == "status"}
    assert status_fields == {"segment", "churn_risk"}


def test_ensure_columns_rejects_type_mismatch():
    """A column with the right title but wrong type must not be silently reused.

    Monday cannot change a column's type after creation, so sending a status
    payload into a text column fails with ColumnValueException on every row.
    """
    from unittest.mock import patch

    import pytest

    import python.load.monday_crm as m

    stale_board = [
        {"id": "text_1", "title": "Segment", "type": "text"},  # should be status
        {"id": "text_2", "title": "Recommended Campaign", "type": "text"},
        {"id": "text_3", "title": "Holiday", "type": "text"},
        {"id": "num_4", "title": "Days Until Holiday", "type": "numbers"},
        {"id": "text_5", "title": "Churn Risk", "type": "text"},  # should be status
        {"id": "num_6", "title": "Lifetime Value", "type": "numbers"},
        {"id": "text_7", "title": "Customer ID", "type": "text"},
    ]

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(
        m, "monday_request", return_value={"boards": [{"columns": stale_board}]}
    ):
        with pytest.raises(RuntimeError, match="wrong type"):
            m.ensure_columns()


def test_ensure_columns_accepts_correct_board():
    from unittest.mock import patch

    import python.load.monday_crm as m

    good_board = [
        {"id": "status_1", "title": "Segment", "type": "status"},
        {"id": "text_2", "title": "Recommended Campaign", "type": "text"},
        {"id": "text_3", "title": "Holiday", "type": "text"},
        {"id": "num_4", "title": "Days Until Holiday", "type": "numbers"},
        {"id": "status_5", "title": "Churn Risk", "type": "status"},
        {"id": "num_6", "title": "Lifetime Value", "type": "numbers"},
        {"id": "text_7", "title": "Customer ID", "type": "text"},
    ]

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(
        m, "monday_request", return_value={"boards": [{"columns": good_board}]}
    ):
        cols = m.ensure_columns()

    assert cols["Segment"] == "status_1"
    assert cols["Churn Risk"] == "status_5"
    assert len(cols) == 7