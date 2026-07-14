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


HOLIDAY = {"holiday_name": "Christmas Day", "days_until_holiday": 166}


def test_campaigns():
    customers, products, orders = _fixtures()
    seg = build_segmentation(customers, orders)
    c360 = build_customer_360(customers, products, orders)
    camp = build_campaigns(seg, HOLIDAY, c360)
    validate_campaigns(camp)

    assert set(camp["customer_id"]) == {"C1", "C2", "C3"}
    assert camp["priority"].between(1, 4).all()
    # Sorted most urgent first so a CRM can be worked top-down.
    assert camp["priority"].is_monotonic_increasing


def test_customer_360_changes_the_recommendation():
    """Two customers identical on segment but different on value must not get
    the same campaign. This is the whole reason Customer 360 feeds the rules."""
    import pandas as pd

    from python.enrich.campaigns import build_campaigns

    seg = pd.DataFrame(
        {
            "customer_id": ["WHALE", "MINNOW"],
            "segment": ["At-Risk Customer", "At-Risk Customer"],
        }
    )
    c360 = pd.DataFrame(
        {
            "customer_id": ["WHALE", "MINNOW"],
            "churn_risk": ["High", "High"],
            "lifetime_value": [14400.0, 90.0],
        }
    )

    camp = build_campaigns(seg, HOLIDAY, c360).set_index("customer_id")

    # Same segment, same churn risk, very different worth.
    assert (
        camp.loc["WHALE", "recommended_campaign"]
        != camp.loc["MINNOW", "recommended_campaign"]
    )
    assert camp.loc["WHALE", "recommended_campaign"] == "Premium Win-Back Campaign"
    assert camp.loc["MINNOW", "recommended_campaign"] == "Win-Back Campaign"


def test_churn_risk_escalates_priority():
    """A VIP slipping away outranks a healthy VIP."""
    import pandas as pd

    from python.enrich.campaigns import build_campaigns

    seg = pd.DataFrame(
        {
            "customer_id": ["LAPSING", "HEALTHY"],
            "segment": ["VIP Customer", "VIP Customer"],
        }
    )
    c360 = pd.DataFrame(
        {
            "customer_id": ["LAPSING", "HEALTHY"],
            "churn_risk": ["High", "Low"],
            "lifetime_value": [8000.0, 8000.0],
        }
    )

    camp = build_campaigns(seg, HOLIDAY, c360).set_index("customer_id")

    assert camp.loc["LAPSING", "priority"] < camp.loc["HEALTHY", "priority"]
    assert camp.loc["LAPSING", "recommended_campaign"] == "Premium Win-Back Campaign"
    assert camp.loc["HEALTHY", "recommended_campaign"] == "Premium Loyalty Campaign"


def test_high_value_returning_customer_is_promoted():
    """Someone spending like a VIP should be treated like one before a
    competitor notices."""
    import pandas as pd

    from python.enrich.campaigns import build_campaigns

    seg = pd.DataFrame(
        {"customer_id": ["RISING"], "segment": ["Returning Customer"]}
    )
    c360 = pd.DataFrame(
        {
            "customer_id": ["RISING"],
            "churn_risk": ["Low"],
            "lifetime_value": [4000.0],  # 80% of the 5000 VIP threshold
        }
    )

    camp = build_campaigns(seg, HOLIDAY, c360)
    assert camp.iloc[0]["recommended_campaign"] == "VIP Upgrade Offer"


def test_campaigns_degrade_without_customer_360():
    """Customer 360 is optional; the engine must still produce valid output."""
    import pandas as pd

    from python.enrich.campaigns import build_campaigns

    seg = pd.DataFrame(
        {"customer_id": ["C1"], "segment": ["VIP Customer"]}
    )
    camp = build_campaigns(seg, HOLIDAY, customer_360=None)
    validate_campaigns(camp)
    assert camp.iloc[0]["recommended_campaign"] == "Premium Loyalty Campaign"


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
        "priority",
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
        {"id": "num_10", "title": "Priority", "type": "numbers"},
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
        {"id": "num_10", "title": "Priority", "type": "numbers"},
    ]

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(
        m, "monday_request", return_value={"boards": [{"columns": good_board}]}
    ):
        cols = m.ensure_columns()

    assert cols["Segment"] == "status_1"
    assert cols["Churn Risk"] == "status_5"
    assert cols["Priority"] == "num_10"
    assert len(cols) == 10


# ---------------------------------------------------------------------------
# Holiday selection
# ---------------------------------------------------------------------------

def _fake_nager_rows(year):
    """Realistic Nager.Date GB payload: a mix of regional and nationwide.

    Dates are built RELATIVE TO TODAY, not hardcoded. A fixture pinned to a
    fixed calendar silently rots: once the real date passes the pinned one, the
    "nearest upcoming holiday" changes and the test fails for reasons that have
    nothing to do with the code.
    """
    import datetime

    today = datetime.date.today()

    # Only the requested year's rows are returned, mirroring the real API.
    offsets = {
        # (name, days from today, nationwide)
        year: [
            ("Imminent Regional Holiday", 1, False),    # tomorrow, regional
            ("Imminent National Holiday", 3, True),     # in 3 days, nationwide
            ("Regional Holiday", 30, False),            # 30 days out, regional
            ("Summer Bank Holiday", 50, True),          # 50 days out, nationwide
            ("Christmas Day", 120, True),               # far out, nationwide
        ],
    }

    rows = []
    for name, days, nationwide in offsets.get(year, []):
        rows.append(
            {
                "holiday_name": name,
                "holiday_date": (today + datetime.timedelta(days=days)).isoformat(),
                "nationwide": nationwide,
            }
        )
    return rows


def test_regional_holidays_are_excluded():
    """A nationwide campaign must not be anchored to a regional holiday."""
    from unittest.mock import patch

    import python.enrich.holiday_api as h

    with patch.object(h, "_fetch_nager", side_effect=_fake_nager_rows), patch.object(
        h.config, "HOLIDAY_API_KEY", ""
    ):
        loose = h.get_holidays(nationwide_only=False, min_lead_days=0)
        strict = h.get_holidays(nationwide_only=True, min_lead_days=0)

    # The regional dates are present when the filter is off...
    assert "Imminent Regional Holiday" in set(loose["holiday_name"])
    assert "Regional Holiday" in set(loose["holiday_name"])

    # ...and gone when it is on.
    names = set(strict["holiday_name"])
    assert "Imminent Regional Holiday" not in names
    assert "Regional Holiday" not in names
    assert strict["nationwide"].all()
    assert len(strict) < len(loose)


def test_min_lead_days_excludes_imminent_holidays():
    """A holiday a day away is accurate but useless: no time to run a campaign."""
    from unittest.mock import patch

    import python.enrich.holiday_api as h

    with patch.object(h, "_fetch_nager", side_effect=_fake_nager_rows), patch.object(
        h.config, "HOLIDAY_API_KEY", ""
    ):
        # No lead-time floor: the nearest date wins, however imminent.
        loose = h.get_holidays(nationwide_only=False, min_lead_days=0)
        assert loose.iloc[0]["days_until_holiday"] < 14
        assert "Imminent" in loose.iloc[0]["holiday_name"]

        # With a floor, nothing inside the window survives.
        strict = h.get_holidays(nationwide_only=False, min_lead_days=14)
        assert (strict["days_until_holiday"] >= 14).all()
        assert not any("Imminent" in n for n in strict["holiday_name"])


def test_get_next_holiday_is_actionable():
    """Both filters together must yield a nationwide, plannable holiday.

    The fixture deliberately offers nearer alternatives that fail one filter
    each: an imminent regional date, an imminent national one, and a regional
    date 30 days out. The only date clearing both filters is 50 days away.
    """
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
    assert camp.iloc[0]["holiday_name"] == "No upcoming holiday"


# ---------------------------------------------------------------------------
# Reverse ETL upsert
# ---------------------------------------------------------------------------

def _board_columns():
    return {
        "Customer ID": "text_cid",
        "Priority": "num_pri",
        "Segment": "status_seg",
        "Recommended Campaign": "text_camp",
        "Holiday": "text_hol",
        "Days Until Holiday": "num_days",
        "Churn Risk": "status_churn",
        "Lifetime Value": "num_ltv",
        "Total Orders": "num_ord",
        "Orders / Month": "num_freq",
    }


def _sync_fixtures():
    import pandas as pd

    campaigns = pd.DataFrame(
        {
            "customer_id": ["C001", "C004"],
            "segment": ["Returning Customer", "At-Risk Customer"],
            "churn_risk": ["Low", "High"],
            "lifetime_value": [2600.0, 90.0],
            "holiday_name": ["Christmas Day", "Christmas Day"],
            "days_until_holiday": [165, 165],
            "recommended_campaign": [
                "Seasonal Discount Campaign",
                "Win-Back Campaign",
            ],
            "priority": [3, 1],
        }
    )
    c360 = pd.DataFrame(
        {
            "customer_id": ["C001", "C004"],
            "total_orders": [3, 1],
            "purchase_frequency": [3.0, 0.17],
            "churn_risk": ["Low", "High"],
            "lifetime_value": [2600.0, 90.0],
        }
    )
    seg = pd.DataFrame(
        {"customer_id": ["C001", "C004"], "customer_name": ["Ada", "Edsger"]}
    )
    return campaigns, c360, seg


def test_repeated_sync_updates_rather_than_duplicates():
    """Reverse ETL is an upsert. Running the pipeline twice must not stack a
    second copy of every customer onto the board."""
    import json
    from unittest.mock import patch

    import python.load.monday_crm as m

    campaigns, c360, seg = _sync_fixtures()

    board = {}          # item_id -> customer_id
    counts = {"create": 0, "update": 0}
    next_id = [1000]

    def fake_request(query, variables=None):
        if "items_page" in query:
            items = [
                {
                    "id": iid,
                    "name": "x",
                    "column_values": [{"id": "text_cid", "text": cid}],
                }
                for iid, cid in board.items()
            ]
            return {"boards": [{"items_page": {"cursor": None, "items": items}}]}
        if "create_item" in query:
            counts["create"] += 1
            cid = json.loads(variables["cols"])["text_cid"]
            next_id[0] += 1
            board[str(next_id[0])] = cid
            return {"create_item": {"id": str(next_id[0]), "name": "x"}}
        if "change_multiple_column_values" in query:
            counts["update"] += 1
            return {"change_multiple_column_values": {"id": variables["item"]}}
        return {}

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(m, "monday_request", side_effect=fake_request), patch.object(
        m, "ensure_columns", return_value=_board_columns()
    ), patch.object(m.time, "sleep"):

        m.sync_campaigns(campaigns, c360, seg)
        assert len(board) == 2
        assert counts["create"] == 2
        assert counts["update"] == 0

        # Second run: same customers, nothing new should be created.
        m.sync_campaigns(campaigns, c360, seg)

    assert len(board) == 2, "second run duplicated the board items"
    assert counts["create"] == 2, "second run created items instead of updating"
    assert counts["update"] == 2, "second run did not update in place"


def test_sync_creates_only_genuinely_new_customers():
    """A customer not yet on the board is created; existing ones are updated."""
    import json
    from unittest.mock import patch

    import pandas as pd

    import python.load.monday_crm as m

    campaigns, c360, seg = _sync_fixtures()

    board = {"999": "C001"}   # C001 already on the board, C004 is not
    counts = {"create": 0, "update": 0}

    def fake_request(query, variables=None):
        if "items_page" in query:
            items = [
                {
                    "id": iid,
                    "name": "x",
                    "column_values": [{"id": "text_cid", "text": cid}],
                }
                for iid, cid in board.items()
            ]
            return {"boards": [{"items_page": {"cursor": None, "items": items}}]}
        if "create_item" in query:
            counts["create"] += 1
            cid = json.loads(variables["cols"])["text_cid"]
            board["1001"] = cid
            return {"create_item": {"id": "1001", "name": "x"}}
        if "change_multiple_column_values" in query:
            counts["update"] += 1
            return {"change_multiple_column_values": {"id": variables["item"]}}
        return {}

    with patch.object(m.config, "MONDAY_API_TOKEN", "x"), patch.object(
        m.config, "MONDAY_BOARD_ID", "123"
    ), patch.object(m, "monday_request", side_effect=fake_request), patch.object(
        m, "ensure_columns", return_value=_board_columns()
    ), patch.object(m.time, "sleep"):

        m.sync_campaigns(campaigns, c360, seg)

    assert counts["create"] == 1, "should create only the new customer"
    assert counts["update"] == 1, "should update the existing customer"
    assert sorted(board.values()) == ["C001", "C004"]