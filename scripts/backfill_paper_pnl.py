"""
One-time backfill: scan all closed paper trades in DynamoDB and seed cache#paper_pnl.

Run from repo root with the backend venv active:
    python scripts/backfill_paper_pnl.py

Set DYNAMO_TABLE_NAME and AWS_REGION if they differ from the defaults below.
"""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

os.environ.setdefault("DYNAMO_TABLE_NAME", "trading-dashboard")
os.environ.setdefault("AWS_REGION", "us-east-1")

import boto3
from boto3.dynamodb.conditions import Key


def _table():
    db = boto3.resource("dynamodb", region_name=os.environ["AWS_REGION"])
    return db.Table(os.environ["DYNAMO_TABLE_NAME"])


def backfill():
    table = _table()

    # Collect all closed trades via the status-date-index GSI (no date filter needed)
    all_closed = []
    resp = table.query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("closed"),
    )
    all_closed.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.query(
            IndexName="status-date-index",
            KeyConditionExpression=Key("status").eq("closed"),
            ExclusiveStartKey=resp["LastEvaluatedKey"],
        )
        all_closed.extend(resp.get("Items", []))

    total = round(sum(float(t.get("realized_pnl", 0) or 0) for t in all_closed), 2)
    print(f"Found {len(all_closed)} closed trades — total P&L: ${total:.2f}")

    # Check if counter already exists
    existing = table.get_item(Key={"trade_id": "cache#paper_pnl"}).get("Item")
    if existing:
        current = float(existing.get("total", 0))
        print(f"cache#paper_pnl already exists with total=${current:.2f}")
        confirm = input("Overwrite? [y/N] ").strip().lower()
        if confirm != "y":
            print("Aborted.")
            return

    table.put_item(Item={
        "trade_id": "cache#paper_pnl",
        "status": "cache",
        "total": Decimal(str(total)),
    })
    print(f"Seeded cache#paper_pnl = ${total:.2f}")


if __name__ == "__main__":
    backfill()
