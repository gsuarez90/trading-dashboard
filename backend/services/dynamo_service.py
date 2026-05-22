import json
import os
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from models.schemas import PaperTrade

ET = ZoneInfo("America/New_York")


def _resource():
    kwargs = {"region_name": os.environ.get("AWS_REGION", "us-east-1")}
    endpoint = os.environ.get("DYNAMO_ENDPOINT_URL")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.resource("dynamodb", **kwargs)


def _table():
    return _resource().Table(os.environ["DYNAMO_TABLE_NAME"])


def ensure_table_exists() -> None:
    """Create the DynamoDB table and GSI if they don't exist. Safe to call repeatedly."""
    name = os.environ["DYNAMO_TABLE_NAME"]
    db = _resource()
    try:
        db.Table(name).load()
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        db.create_table(
            TableName=name,
            AttributeDefinitions=[
                {"AttributeName": "trade_id", "AttributeType": "S"},
                {"AttributeName": "status",   "AttributeType": "S"},
                {"AttributeName": "date",     "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "trade_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-date-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "date",   "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        db.Table(name).wait_until_exists()


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


def get_pending_trades_for_date(date: str) -> list[dict]:
    """All pending (unfilled) orders for a given date. Used by price monitor and EOD handler."""
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("pending") & Key("date").eq(date),
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


# ── Guardrail events ──────────────────────────────────────────────────────────


def log_guardrail_event(
    ticker: str,
    rules_triggered: list[str],
    messages: list[str],
    date: str | None = None,
    timestamp: str | None = None,
) -> None:
    """Persist a guardrail trigger event. Stored in the same table as trades,
    queryable via the status-date-index GSI using status='guardrail_event'."""
    now = datetime.now(tz=ET)
    _table().put_item(Item={
        "trade_id": str(uuid.uuid4()),
        "record_type": "guardrail_event",
        "status": "guardrail_event",
        "date": date or now.strftime("%Y-%m-%d"),
        "timestamp": timestamp or now.isoformat(),
        "ticker": ticker,
        "rules_triggered": rules_triggered,
        "messages": messages,
    })


# ── Cache (scanner / sentiment pre-compute) ───────────────────────────────────


def put_cache(key: str, payload: list | dict) -> None:
    """Store a named cache entry. Uses trade_id='cache#<key>' as the hash key."""
    now = datetime.now(tz=ET)
    _table().put_item(Item={
        "trade_id": f"cache#{key}",
        "status": "cache",
        "date": now.strftime("%Y-%m-%d"),
        "cached_at": now.isoformat(),
        "payload": json.dumps(payload, default=str),
    })


def get_cache(key: str) -> tuple[list | dict | None, str | None]:
    """Return (payload, cached_at_iso) or (None, None) if not found."""
    resp = _table().get_item(Key={"trade_id": f"cache#{key}"})
    item = resp.get("Item")
    if not item:
        return None, None
    return json.loads(item["payload"]), item.get("cached_at")


def get_guardrail_events_by_date(date: str) -> list[dict]:
    """Fetch all guardrail events for a given date, newest first."""
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("guardrail_event") & Key("date").eq(date),
    )
    events = [_from_item(item) for item in response.get("Items", [])]
    return sorted(events, key=lambda e: e.get("timestamp", ""), reverse=True)
