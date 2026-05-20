import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Attr, Key

from models.schemas import PaperTrade


def _table():
    dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return dynamodb.Table(os.environ["DYNAMO_TABLE_NAME"])


def _to_item(trade: PaperTrade) -> dict:
    """Convert PaperTrade to a DynamoDB item, casting floats to Decimal."""
    raw = trade.model_dump()
    item = {}
    for k, v in raw.items():
        if isinstance(v, float):
            item[k] = Decimal(str(v))
        elif v is None:
            pass  # DynamoDB doesn't store None — omit nulls
        else:
            item[k] = v
    return item


def _from_item(item: dict) -> dict:
    """Cast Decimal values back to float for API responses."""
    result = {}
    for k, v in item.items():
        if isinstance(v, Decimal):
            result[k] = float(v)
        else:
            result[k] = v
    return result


# ── Write ─────────────────────────────────────────────────────────────────────


def put_trade(trade: PaperTrade) -> None:
    _table().put_item(Item=_to_item(trade))


def update_trade(trade_id: str, updates: dict) -> None:
    """Partial update — pass only the fields to change."""
    expressions = []
    attr_values = {}
    attr_names = {}

    for i, (key, value) in enumerate(updates.items()):
        placeholder = f":v{i}"
        name_placeholder = f"#k{i}"
        expressions.append(f"{name_placeholder} = {placeholder}")
        attr_names[name_placeholder] = key
        if isinstance(value, float):
            attr_values[placeholder] = Decimal(str(value))
        else:
            attr_values[placeholder] = value

    _table().update_item(
        Key={"trade_id": trade_id},
        UpdateExpression="SET " + ", ".join(expressions),
        ExpressionAttributeValues=attr_values,
        ExpressionAttributeNames=attr_names,
    )


# ── Read ──────────────────────────────────────────────────────────────────────


def get_trade(trade_id: str) -> dict | None:
    response = _table().get_item(Key={"trade_id": trade_id})
    item = response.get("Item")
    return _from_item(item) if item else None


def get_open_trades() -> list[dict]:
    """All trades with status='open'. Used by price monitor and guardrails."""
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("open"),
    )
    return [_from_item(item) for item in response.get("Items", [])]


def get_trades_by_date(date: str) -> list[dict]:
    """All trades for a given date (YYYY-MM-DD). Used for daily context and P&L."""
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("open") & Key("date").eq(date),
    )
    items = response.get("Items", [])

    # Also fetch closed trades for the date via scan (GSI only indexes open)
    closed = _table().scan(
        FilterExpression=Attr("date").eq(date) & Attr("status").ne("open"),
    )
    items.extend(closed.get("Items", []))
    return [_from_item(item) for item in items]


def get_realized_pnl_today(date: str) -> float:
    """Sum of realized_pnl for all closed trades on a given date."""
    trades = get_trades_by_date(date)
    return round(
        sum(t.get("realized_pnl", 0) or 0 for t in trades if t.get("status") != "open"),
        2,
    )


def get_trade_count_today(date: str) -> int:
    """Number of trades opened today. Used by the daily trade limit guardrail."""
    trades = get_trades_by_date(date)
    return len(trades)
