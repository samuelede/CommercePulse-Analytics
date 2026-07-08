"""Reverse ETL: sync campaign recommendations into Monday CRM.

Uses the Monday.com GraphQL API. Each customer becomes a board item with
column values for segment, campaign, holiday, and churn context.
"""
import json

import requests

from python.utils.config import config
from python.utils.db import get_logger

logger = get_logger(__name__)

TIMEOUT = 30


def _headers():
    return {
        "Authorization": config.MONDAY_API_TOKEN,
        "Content-Type": "application/json",
        "API-Version": "2024-01",
    }


def _post(query, variables=None):
    resp = requests.post(
        config.MONDAY_API_URL,
        json={"query": query, "variables": variables or {}},
        headers=_headers(),
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    if "errors" in payload:
        raise RuntimeError(payload["errors"])
    return payload["data"]


def create_item(board_id, item_name, column_values):
    query = """
    mutation ($board: ID!, $name: String!, $cols: JSON!) {
      create_item (board_id: $board, item_name: $name, column_values: $cols) {
        id
      }
    }
    """
    variables = {
        "board": str(board_id),
        "name": item_name,
        "cols": json.dumps(column_values),
    }
    return _post(query, variables)


def sync_campaigns(campaigns, customer_360=None):
    """Push campaign recommendations to the configured Monday board.

    column_values keys must match the column IDs configured on the board.
    Adjust the mapping below to your board's actual column IDs.
    """
    if not config.MONDAY_API_TOKEN or not config.MONDAY_BOARD_ID:
        logger.error("Monday token or board id missing; skipping sync")
        return 0

    lookup = {}
    if customer_360 is not None:
        lookup = customer_360.set_index("customer_id").to_dict("index")

    pushed = 0
    for _, row in campaigns.iterrows():
        cid = row["customer_id"]
        meta = lookup.get(cid, {})
        column_values = {
            "text_segment": str(row["segment"]),
            "text_campaign": str(row["recommended_campaign"]),
            "text_holiday": str(row["holiday_name"]),
            "numbers_days": int(row["days_until_holiday"]),
            "text_churn": str(meta.get("churn_risk", "")),
            "numbers_ltv": float(meta.get("lifetime_value", 0) or 0),
        }
        try:
            create_item(config.MONDAY_BOARD_ID, str(cid), column_values)
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to push %s: %s", cid, exc)

    logger.info("Synced %d items to Monday CRM", pushed)
    return pushed
