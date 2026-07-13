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
                {"AttributeName": "status", "AttributeType": "S"},
                {"AttributeName": "date", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "trade_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "status-date-index",
                    "KeySchema": [
                        {"AttributeName": "status", "KeyType": "HASH"},
                        {"AttributeName": "date", "KeyType": "RANGE"},
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


def get_shadow_open_trades() -> list[dict]:
    """All shadow (calibration-only) option trades with status='shadow_open'.

    Deliberately a separate status value from 'open' — this query, unlike
    get_open_trades(), is never consulted by guardrails, get_trades_by_date(),
    or the real dashboard, so shadow calibration data can never leak into
    real daily_loss_limit/daily_trade_limit counters or P&L
    (intraday-options-pivot-plan.md §7).
    """
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("shadow_open"),
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
    """All trade records for a given date. Excludes guardrail events and cache entries."""
    items = []
    for status in ("open", "closed", "pending", "expired", "cancelled"):
        resp = _table().query(
            IndexName="status-date-index",
            KeyConditionExpression=Key("status").eq(status) & Key("date").eq(date),
        )
        items.extend(resp.get("Items", []))
    return [_from_item(item) for item in items]


def get_realized_pnl_today(date: str) -> float:
    """Sum of realized_pnl for all closed trades on a given date."""
    trades = get_trades_by_date(date)
    return round(
        sum(t.get("realized_pnl", 0) or 0 for t in trades if t.get("status") != "open"),
        2,
    )


def get_trade_count_today(date: str) -> int:
    """Number of trade orders placed today. Counts open/closed/pending; not expired (never filled)."""
    trades = get_trades_by_date(date)
    return sum(1 for t in trades if t.get("status") in {"open", "closed", "pending"})


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
    _table().put_item(
        Item={
            "trade_id": str(uuid.uuid4()),
            "record_type": "guardrail_event",
            "status": "guardrail_event",
            "date": date or now.strftime("%Y-%m-%d"),
            "timestamp": timestamp or now.isoformat(),
            "ticker": ticker,
            "rules_triggered": rules_triggered,
            "messages": messages,
        }
    )


# ── Cache (scanner / sentiment pre-compute) ───────────────────────────────────


def put_cache(key: str, payload: list | dict) -> None:
    """Store a named cache entry. Uses trade_id='cache#<key>' as the hash key."""
    now = datetime.now(tz=ET)
    _table().put_item(
        Item={
            "trade_id": f"cache#{key}",
            "status": "cache",
            "date": now.strftime("%Y-%m-%d"),
            "cached_at": now.isoformat(),
            "payload": json.dumps(payload, default=str),
        }
    )


def get_cache(key: str) -> tuple[list | dict | None, str | None]:
    """Return (payload, cached_at_iso) or (None, None) if not found."""
    resp = _table().get_item(Key={"trade_id": f"cache#{key}"})
    item = resp.get("Item")
    if not item:
        return None, None
    return json.loads(item["payload"]), item.get("cached_at")


def increment_paper_pnl_cumulative(amount: float) -> None:
    """Atomically add amount to the all-time paper P&L running total."""
    _table().update_item(
        Key={"trade_id": "cache#paper_pnl"},
        UpdateExpression="SET #status = if_not_exists(#status, :s) ADD #total :amt",
        ExpressionAttributeNames={"#total": "total", "#status": "status"},
        ExpressionAttributeValues={
            ":amt": Decimal(str(round(amount, 2))),
            ":s": "cache",
        },
    )


def get_paper_pnl_cumulative() -> float:
    """Return all-time realized paper P&L. Returns 0.0 if the counter has not been seeded."""
    resp = _table().get_item(Key={"trade_id": "cache#paper_pnl"})
    item = resp.get("Item")
    if not item:
        return 0.0
    return float(item.get("total", Decimal("0")))


def get_guardrail_events_by_date(date: str) -> list[dict]:
    """Fetch all guardrail events for a given date, newest first."""
    response = _table().query(
        IndexName="status-date-index",
        KeyConditionExpression=Key("status").eq("guardrail_event") & Key("date").eq(date),
    )
    events = [_from_item(item) for item in response.get("Items", [])]
    return sorted(events, key=lambda e: e.get("timestamp", ""), reverse=True)
