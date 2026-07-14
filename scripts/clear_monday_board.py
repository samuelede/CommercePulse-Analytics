"""Delete every item from the Monday board.

Needed once, to clear duplicates left by an earlier append-only sync. After
that the pipeline upserts and the board stays clean, so this should not be
needed again.

    PYTHONPATH=. python scripts/clear_monday_board.py          # dry run
    PYTHONPATH=. python scripts/clear_monday_board.py --yes    # actually delete
"""
import argparse
import sys
import time

from python.load.monday_crm import monday_request
from python.utils.config import config

RATE_LIMIT_SLEEP = 0.4


def all_items():
    query = """
    query ($board: ID!, $cursor: String) {
      boards (ids: [$board]) {
        items_page (limit: 100, cursor: $cursor) {
          cursor
          items { id name }
        }
      }
    }
    """
    items, cursor = [], None
    while True:
        data = monday_request(
            query, {"board": str(config.MONDAY_BOARD_ID), "cursor": cursor}
        )
        boards = data.get("boards") or []
        if not boards:
            break
        page = boards[0]["items_page"]
        items.extend(page["items"])
        cursor = page.get("cursor")
        if not cursor:
            break
    return items


def delete_item(item_id):
    query = """
    mutation ($item: ID!) {
      delete_item (item_id: $item) { id }
    }
    """
    monday_request(query, {"item": str(item_id)})


def main():
    parser = argparse.ArgumentParser(description="Clear the Monday board")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag it is a dry run.",
    )
    args = parser.parse_args()

    if not config.MONDAY_API_TOKEN or not config.MONDAY_BOARD_ID:
        sys.exit("Set MONDAY_API_TOKEN and MONDAY_BOARD_ID in .env first")

    items = all_items()
    if not items:
        print("Board is already empty.")
        return

    print(f"Board {config.MONDAY_BOARD_ID} holds {len(items)} item(s):")
    for it in items[:20]:
        print(f"  {it['id']}  {it['name']}")
    if len(items) > 20:
        print(f"  ... and {len(items) - 20} more")

    if not args.yes:
        print(f"\nDry run. Re-run with --yes to delete all {len(items)} items.")
        return

    print()
    deleted = 0
    for it in items:
        try:
            delete_item(it["id"])
            deleted += 1
            print(f"  deleted {it['name']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {it['name']}: {exc}")
        time.sleep(RATE_LIMIT_SLEEP)

    print(f"\nDeleted {deleted} of {len(items)} items.")
    print("Now run: python -m python.pipeline")


if __name__ == "__main__":
    main()