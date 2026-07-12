"""Verify Monday CRM credentials and board reachability.

    PYTHONPATH=. python scripts/check_monday.py

Exit codes: 0 OK, 1 hard failure, 2 not configured.
"""
import sys

from python.utils.config import config


def main():
    if not config.MONDAY_API_TOKEN:
        print("  [WARN] MONDAY_API_TOKEN not set in .env")
        return 2
    if not config.MONDAY_BOARD_ID:
        print("  [WARN] MONDAY_BOARD_ID not set in .env")
        return 2

    from python.load.monday_crm import COLUMN_PLAN, monday_request

    try:
        me = monday_request("query { me { name email } }")["me"]
        print(f"  [PASS] token valid  ({me['name']} <{me['email']}>)")
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] token rejected: {exc}")
        return 1

    query = """
    query ($b: [ID!]) {
      boards(ids: $b) { name columns { id title type } }
    }
    """
    try:
        boards = monday_request(
            query, {"b": [str(config.MONDAY_BOARD_ID)]}
        )["boards"]
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] board query failed: {exc}")
        return 1

    if not boards:
        print(f"  [FAIL] board {config.MONDAY_BOARD_ID} not found or no access")
        return 1

    board = boards[0]
    titles = {c["title"] for c in board["columns"]}
    print(
        f"  [PASS] board reachable  "
        f"('{board['name']}', {len(board['columns'])} columns)"
    )

    wanted = {title for title, _ in COLUMN_PLAN.values()}
    missing = wanted - titles
    if missing:
        print(f"  [INFO] {len(missing)} column(s) will be created on first sync:")
        for m in sorted(missing):
            print(f"           {m}")
    else:
        print("  [PASS] all required columns already present")

    return 0


if __name__ == "__main__":
    sys.exit(main())