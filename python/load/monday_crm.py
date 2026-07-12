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
    "segment":              ("Segment",              "status"),
    "recommended_campaign": ("Recommended Campaign", "text"),
    "holiday_name":         ("Holiday",              "text"),
    "days_until_holiday":   ("Days Until Holiday",   "numbers"),
    "churn_risk":           ("Churn Risk",           "status"),
    "lifetime_value":       ("Lifetime Value",       "numbers"),
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

    title_to_id = {c["title"]: c["id"] for c in boards[0]["columns"]}

    create = """
    mutation ($board: ID!, $title: String!, $type: ColumnType!) {
      create_column (board_id: $board, title: $title, column_type: $type) {
        id title
      }
    }
    """
    for title, col_type in COLUMN_PLAN.values():
        if title not in title_to_id:
            new_col = monday_request(
                create,
                {
                    "board": str(config.MONDAY_BOARD_ID),
                    "title": title,
                    "type": col_type,
                },
            )["create_column"]
            title_to_id[title] = new_col["id"]
            logger.info("Created column '%s' (id=%s)", title, new_col["id"])

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


def sync_campaigns(campaigns, customer_360=None, segmentation=None):
    """Publish campaign recommendations to the configured Monday board.

    campaigns     : customer_id, segment, holiday_name, days_until_holiday,
                    recommended_campaign
    customer_360  : optional, supplies churn_risk and lifetime_value
    segmentation  : optional, supplies customer_name for the item title
    """
    if not config.MONDAY_API_TOKEN or not config.MONDAY_BOARD_ID:
        logger.error("MONDAY_API_TOKEN or MONDAY_BOARD_ID missing; skipping sync")
        return 0

    title_to_id = ensure_columns()

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

    pushed = 0
    for _, row in campaigns.iterrows():
        cid = row["customer_id"]
        meta = c360.get(cid, {})

        record = {
            "customer_id": cid,
            "segment": row["segment"],
            "recommended_campaign": row["recommended_campaign"],
            "holiday_name": row["holiday_name"],
            "days_until_holiday": row["days_until_holiday"],
            "churn_risk": meta.get("churn_risk"),
            "lifetime_value": meta.get("lifetime_value"),
        }

        column_values = {}
        for field, (title, col_type) in COLUMN_PLAN.items():
            column_values[title_to_id[title]] = value_for_column(
                col_type, record[field]
            )

        # Prefer a human-readable item title; fall back to the id.
        item_name = str(names.get(cid, cid))

        try:
            monday_request(
                create_item,
                {
                    "board": str(config.MONDAY_BOARD_ID),
                    "name": item_name,
                    # column_values must be a JSON *string*
                    "cols": json.dumps(column_values),
                },
            )
            pushed += 1
        except (requests.RequestException, RuntimeError) as exc:
            logger.warning("Failed to push %s: %s", cid, exc)

        time.sleep(RATE_LIMIT_SLEEP)

    logger.info("Synced %d of %d items to Monday CRM", pushed, len(campaigns))
    return pushed