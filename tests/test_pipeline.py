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
    c1 = c360[c360.customer_id == "C1"].iloc[0]
    assert c1["lifetime_value"] == 6300
    assert c1["total_orders"] == 3
    assert c1["preferred_category"] == "Electronics"
    # C3 has no orders at all
    c3 = c360[c360.customer_id == "C3"].iloc[0]
    assert c3["total_orders"] == 0
    assert c3["lifetime_value"] == 0
    assert c3["purchase_frequency"] == 0
    assert c3["churn_risk"] == "High"


def test_purchase_frequency_is_a_rate_not_a_count():
    """Two customers with identical order counts but different tenures must
    get different frequencies. A bare count cannot distinguish them."""
    import pandas as pd

    from python.transform.customer_360 import build_customer_360

    customers = pd.DataFrame(
        {"customer_id": ["FAST", "SLOW"], "name": ["Fast", "Slow"]}
    )
    products = pd.DataFrame(
        {"product_id": ["P1"], "category": ["Electronics"]}
    )

    now = pd.Timestamp.now("UTC").tz_localize(None)
    rows = []
    # FAST: 4 orders in the last ~3 weeks
    for i in range(4):
        rows.append(
            {
                "order_id": f"F{i}",
                "customer_id": "FAST",
                "product_id": "P1",
                "amount": 100,
                "payment_status": "completed",
                "created_at": now - pd.Timedelta(days=i * 7),
            }
        )
    # SLOW: 4 orders spread over ~2 years
    for i in range(4):
        rows.append(
            {
                "order_id": f"S{i}",
                "customer_id": "SLOW",
                "product_id": "P1",
                "amount": 100,
                "payment_status": "completed",
                "created_at": now - pd.Timedelta(days=i * 180),
            }
        )
    orders = pd.DataFrame(rows)

    c360 = build_customer_360(customers, products, orders)
    fast = c360[c360.customer_id == "FAST"].iloc[0]
    slow = c360[c360.customer_id == "SLOW"].iloc[0]

    # Same raw count...
    assert fast["total_orders"] == slow["total_orders"] == 4
    # ...but very different rates.
    assert fast["purchase_frequency"] > slow["purchase_frequency"]
    assert fast["purchase_frequency"] > 3.0   # ~4 orders in ~1 month
    assert slow["purchase_frequency"] < 1.0   # ~4 orders over ~18 months


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
        "total_orders",
        "purchase_frequency",
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
        {"id": "num_8", "title": "Total Orders", "type": "numbers"},
        {"id": "num_9", "title": "Orders / Month", "type": "numbers"},
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
        {"id": "num_8", "title": "Total Orders", "type": "numbers"},
        {"id": "num_9", "title": "Orders / Month", "type": "numbers"},
    ]

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(
        m, "monday_request", return_value={"boards": [{"columns": good_board}]}
    ):
        cols = m.ensure_columns()

    assert cols["Segment"] == "status_1"
    assert cols["Churn Risk"] == "status_5"
    assert cols["Total Orders"] == "num_8"
    assert len(cols) == 9


# ---------------------------------------------------------------------------
# Holiday selection
# ---------------------------------------------------------------------------

def _fake_nager_rows(year):
    """Realistic Nager.Date GB payload: a mix of regional and nationwide."""
    by_year = {
        2026: [
            ("Battle of the Boyne", f"{year}-07-13", False),   # NI only
            ("Scottish Summer Bank Holiday", f"{year}-08-03", False),  # Scotland
            ("Summer Bank Holiday", f"{year}-08-31", True),
            ("St Andrew's Day", f"{year}-11-30", False),       # Scotland
            ("Christmas Day", f"{year}-12-25", True),
        ],
        2027: [("New Year's Day", "2027-01-01", True)],
    }
    return [
        {"holiday_name": n, "holiday_date": d, "nationwide": w}
        for n, d, w in by_year.get(year, [])
    ]


def test_regional_holidays_are_excluded():
    """A nationwide campaign must not be anchored to a regional holiday."""
    from unittest.mock import patch

    import python.enrich.holiday_api as h

    with patch.object(h, "_fetch_nager", side_effect=_fake_nager_rows), patch.object(
        h.config, "HOLIDAY_API_KEY", ""
    ):
        df = h.get_holidays(nationwide_only=True, min_lead_days=0)

    names = set(df["holiday_name"])
    assert "Battle of the Boyne" not in names
    assert "St Andrew's Day" not in names
    assert df["nationwide"].all()


def test_min_lead_days_excludes_imminent_holidays():
    """A holiday a day away is accurate but useless: no time to run a campaign."""
    from unittest.mock import patch

    import python.enrich.holiday_api as h

    with patch.object(h, "_fetch_nager", side_effect=_fake_nager_rows), patch.object(
        h.config, "HOLIDAY_API_KEY", ""
    ):
        # No lead-time floor: the imminent regional date is the nearest.
        loose = h.get_holidays(nationwide_only=False, min_lead_days=0)
        assert loose.iloc[0]["holiday_name"] == "Battle of the Boyne"
        assert loose.iloc[0]["days_until_holiday"] < 14

        # With a floor, nothing inside the window survives.
        strict = h.get_holidays(nationwide_only=False, min_lead_days=14)
        assert (strict["days_until_holiday"] >= 14).all()
        assert "Battle of the Boyne" not in set(strict["holiday_name"])


def test_get_next_holiday_is_actionable():
    """Both filters together must yield a nationwide, plannable holiday."""
    from unittest.mock import patch

    import python.enrich.holiday_api as h

    with patch.object(h, "_fetch_nager", side_effect=_fake_nager_rows), patch.object(
        h.config, "HOLIDAY_API_KEY", ""
    ):
        holiday = h.get_next_holiday(nationwide_only=True, min_lead_days=14)

    assert holiday is not None
    assert holiday["holiday_name"] == "Summer Bank Holiday"
    assert holiday["days_until_holiday"] >= 14


def test_campaigns_handle_no_holiday_found():
    """If no holiday clears the filters, campaigns still generate."""
    import pandas as pd

    from python.enrich.campaigns import build_campaigns

    seg = pd.DataFrame(
        {"customer_id": ["C1"], "segment": ["VIP Customer"]}
    )
    camp = build_campaigns(seg, holiday=None)

    assert len(camp) == 1
    assert camp.iloc[0]["recommended_campaign"] == "Premium Loyalty Campaign"
    assert camp["holiday_name"].notna().all()