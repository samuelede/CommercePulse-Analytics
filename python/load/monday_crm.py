"""Reverse ETL: publish CommercePulse customer intelligence into Monday CRM.

The board is self-configuring. On each run ensure_columns() reads the board,
creates any missing column, and returns a live title -> id map, so column IDs
never need to be hardcoded or copied by hand.

Monday exposes a single GraphQL endpoint; queries read and mutations write.

API reference:
  Basics ............. https://developer.monday.com/api-reference/docs/basics
  Authentication ..... https://developer.monday.com/api-reference/docs/authentication
  Rate limits ........ https://developer.monday.com/api-reference/docs/rate-limits
  Columns ............ https://developer.monday.com/api-reference/reference/columns
  Column types ....... https://developer.monday.com/api-reference/reference/column-types-reference
  Column values ...... https://developer.monday.com/api-reference/reference/column-values-v2
  Items .............. https://developer.monday.com/api-reference/reference/items
"""
import json
import time

import pandas as pd
import requests

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

TIMEOUT = 30
RATE_LIMIT_SLEEP = 0.4  # Monday throttles aggressive writes

# Field name -> (Monday column title, Monday column type).
# Segment and Churn Risk are status columns so the board is filterable and
# colour-coded for business users. The item name carries the customer name.
COLUMN_PLAN = {
    "customer_id":          ("Customer ID",          "text"),
    "priority":             ("Priority",             "numbers"),
    "segment":              ("Segment",              "status"),
    "recommended_campaign": ("Recommended Campaign", "text"),
    "holiday_name":         ("Holiday",              "text"),
    "days_until_holiday":   ("Days Until Holiday",   "numbers"),
    "churn_risk":           ("Churn Risk",           "status"),
    "lifetime_value":       ("Lifetime Value",       "numbers"),
    "total_orders":         ("Total Orders",         "numbers"),
    "purchase_frequency":   ("Orders / Month",       "numbers"),
}


def monday_request(query, variables=None):
    """Send one GraphQL request and return the data payload."""
    response = requests.post(
        config.MONDAY_API_URL,
        json={"query": query, "variables": variables or {}},
        headers={
            "Authorization": config.MONDAY_API_TOKEN,
            "Content-Type": "application/json",
            "API-Version": "2023-10",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    result = response.json()
    if "errors" in result:
        raise RuntimeError(json.dumps(result["errors"], indent=2))
    return result["data"]


def ensure_columns():
    """Return {column title: column id}, creating any column that is missing.

    Monday assigns its own internal column ids at creation time, so the board
    must always be read back rather than assumed.

    Columns are matched on title AND type. A title that exists with the wrong
    type is a real problem: sending a status-shaped value into a text column
    fails with ColumnValueException. This happens when COLUMN_PLAN changes
    after a board was already built. Rather than silently mismatching, raise
    with instructions.
    """
    read = """
    query ($board: [ID!]) {
      boards (ids: $board) { columns { id title type } }
    }
    """
    boards = monday_request(read, {"board": [str(config.MONDAY_BOARD_ID)]})["boards"]
    if not boards:
        raise RuntimeError(
            f"Board {config.MONDAY_BOARD_ID} not found or not accessible"
        )

    existing = {c["title"]: c for c in boards[0]["columns"]}

    create = """
    mutation ($board: ID!, $title: String!, $type: ColumnType!) {
      create_column (board_id: $board, title: $title, column_type: $type) {
        id title type
      }
    }
    """

    title_to_id = {}
    mismatched = []

    for title, want_type in COLUMN_PLAN.values():
        col = existing.get(title)
        if col is None:
            new_col = monday_request(
                create,
                {
                    "board": str(config.MONDAY_BOARD_ID),
                    "title": title,
                    "type": want_type,
                },
            )["create_column"]
            title_to_id[title] = new_col["id"]
            logger.info(
                "Created column '%s' (%s, id=%s)",
                title,
                want_type,
                new_col["id"],
            )
        elif col["type"] != want_type:
            mismatched.append((title, col["type"], want_type, col["id"]))
        else:
            title_to_id[title] = col["id"]

    if mismatched:
        lines = "\n".join(
            f"    '{t}': board has '{have}', pipeline expects '{want}' (id={cid})"
            for t, have, want, cid in mismatched
        )
        raise RuntimeError(
            "Monday board has columns with the wrong type:\n"
            f"{lines}\n\n"
            "Monday cannot change a column's type after creation. Delete these "
            "columns in the board UI (column header dropdown > Delete) and "
            "rerun; they will be recreated with the correct type. Deleting the "
            "items as well gives the cleanest result."
        )

    return title_to_id


def value_for_column(col_type, raw_value):
    """Coerce a value into the JSON shape Monday expects for that column type.

    Each type serializes differently; numbers in particular must be sent as
    strings, not as numeric literals.
    """
    if raw_value is None or (isinstance(raw_value, float) and pd.isna(raw_value)):
        return "" if col_type != "numbers" else "0"

    if col_type == "status":
        return {"label": str(raw_value)}
    if col_type == "date":
        return {"date": str(raw_value)}
    if col_type == "numbers":
        return str(raw_value)
    return str(raw_value)


def fetch_existing_items(customer_id_column):
    """Return {customer_id: monday_item_id} for everything already on the board.

    Reverse ETL is an upsert: a customer already on the board must be updated
    in place, not appended again. Matching is on the Customer ID column rather
    than the item name, since the customer id is the stable business key and
    names are not guaranteed unique.

    Paginated: boards outgrow a single page quickly.
    """
    query = """
    query ($board: ID!, $cursor: String) {
      boards (ids: [$board]) {
        items_page (limit: 100, cursor: $cursor) {
          cursor
          items {
            id
            name
            column_values (ids: [$colId]) { id text }
          }
        }
      }
    }
    """
    # column_values takes the id list as a variable; inline it since Monday's
    # schema wants [String!] here and mixing it with the cursor is fiddly.
    query = query.replace("$colId", f'"{customer_id_column}"')

    existing = {}
    cursor = None

    while True:
        data = monday_request(
            query, {"board": str(config.MONDAY_BOARD_ID), "cursor": cursor}
        )
        boards = data.get("boards") or []
        if not boards:
            break

        page = boards[0]["items_page"]
        for item in page["items"]:
            cid = None
            for col in item.get("column_values", []):
                if col["id"] == customer_id_column:
                    cid = (col.get("text") or "").strip()
            if cid:
                existing[cid] = item["id"]

        cursor = page.get("cursor")
        if not cursor:
            break

    logger.info("Board already holds %d item(s)", len(existing))
    return existing


def sync_campaigns(campaigns, customer_360=None, segmentation=None):
    """Upsert campaign recommendations onto the configured Monday board.

    This is an upsert, not an append. A customer already on the board is
    updated in place; only genuinely new customers create items. Blindly
    calling create_item on every run stacks a fresh copy of every customer on
    top of the last, which is not a sync but an append log: the board fills
    with contradictory duplicates and nobody can trust any row.

    Matching is on the Customer ID column, the stable business key.

    campaigns     : customer_id, segment, churn_risk, lifetime_value,
                    holiday_name, days_until_holiday, recommended_campaign,
                    priority
    customer_360  : optional; supplies total_orders and purchase_frequency
    segmentation  : optional; supplies customer_name for the item title
    """
    if not config.MONDAY_API_TOKEN or not config.MONDAY_BOARD_ID:
        logger.error("MONDAY_API_TOKEN or MONDAY_BOARD_ID missing; skipping sync")
        return 0

    title_to_id = ensure_columns()
    cid_column = title_to_id[COLUMN_PLAN["customer_id"][0]]
    existing = fetch_existing_items(cid_column)

    c360 = (
        customer_360.set_index("customer_id").to_dict("index")
        if customer_360 is not None
        else {}
    )
    names = (
        segmentation.set_index("customer_id")["customer_name"].to_dict()
        if segmentation is not None
        else {}
    )

    create_item = """
    mutation ($board: ID!, $name: String!, $cols: JSON!) {
      create_item (
        board_id: $board,
        item_name: $name,
        column_values: $cols,
        create_labels_if_missing: true
      ) { id name }
    }
    """

    update_item = """
    mutation ($board: ID!, $item: ID!, $cols: JSON!) {
      change_multiple_column_values (
        board_id: $board,
        item_id: $item,
        column_values: $cols,
        create_labels_if_missing: true
      ) { id name }
    }
    """

    created = updated = failed = 0

    for _, row in campaigns.iterrows():
        cid = str(row["customer_id"])
        meta = c360.get(cid, {})

        # churn_risk and lifetime_value ride on the campaigns row itself (the
        # rule engine consumes them), so prefer those and fall back to the
        # Customer 360 lookup only for fields campaigns does not carry.
        record = {
            "customer_id": cid,
            "priority": row.get("priority"),
            "segment": row["segment"],
            "recommended_campaign": row["recommended_campaign"],
            "holiday_name": row["holiday_name"],
            "days_until_holiday": row["days_until_holiday"],
            "churn_risk": row.get("churn_risk", meta.get("churn_risk")),
            "lifetime_value": row.get(
                "lifetime_value", meta.get("lifetime_value")
            ),
            "total_orders": meta.get("total_orders"),
            "purchase_frequency": meta.get("purchase_frequency"),
        }

        column_values = {}
        for field, (title, col_type) in COLUMN_PLAN.items():
            column_values[title_to_id[title]] = value_for_column(
                col_type, record[field]
            )

        item_name = str(names.get(cid, cid))
        item_id = existing.get(cid)

        try:
            if item_id:
                monday_request(
                    update_item,
                    {
                        "board": str(config.MONDAY_BOARD_ID),
                        "item": str(item_id),
                        # column_values must be a JSON *string*
                        "cols": json.dumps(column_values),
                    },
                )
                updated += 1
            else:
                monday_request(
                    create_item,
                    {
                        "board": str(config.MONDAY_BOARD_ID),
                        "name": item_name,
                        "cols": json.dumps(column_values),
                    },
                )
                created += 1
        except RuntimeError as exc:
            # A schema-level error will fail identically for every row, so stop
            # rather than hammering the API with the same broken payload.
            if "ColumnValueException" in str(exc):
                raise RuntimeError(
                    f"Monday rejected the column values for {cid}. This is a "
                    "schema problem and will fail for every row, so the sync "
                    f"is stopping.\n\n{exc}"
                ) from exc
            logger.warning("Failed to sync %s: %s", cid, exc)
            failed += 1
        except requests.RequestException as exc:
            logger.warning("Failed to sync %s: %s", cid, exc)
            failed += 1

        time.sleep(RATE_LIMIT_SLEEP)

    pushed = created + updated
    logger.info(
        "Synced %d of %d items to Monday CRM (%d created, %d updated, %d failed)",
        pushed,
        len(campaigns),
        created,
        updated,
        failed,
    )
    return pushed