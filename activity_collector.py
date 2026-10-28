import json
import os
from pathlib import Path

from dotenv import load_dotenv
from polymarket_us import PolymarketUS


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"
OUTPUT_FILE = DATA_DIR / "activities_normalized.json"

load_dotenv(PROJECT_DIR / ".env")

KEY_ID = os.getenv("POLYMARKET_KEY_ID")
SECRET_KEY = os.getenv("POLYMARKET_SECRET_KEY")

PAGE_SIZE = 100
MAX_PAGES = 10000

REQUESTED_ACTIVITY_TYPES = [
    "ACTIVITY_TYPE_TRADE",
    "ACTIVITY_TYPE_POSITION_RESOLUTION",
    "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
    "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
    "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
]

CASH_ACTIVITY_TYPES = {
    "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
    "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
    "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
}


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def to_dict(value):
    """Convert SDK model objects and nested values into plain dictionaries."""
    if isinstance(value, dict):
        return {
            key: to_dict(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [to_dict(item) for item in value]

    if hasattr(value, "model_dump"):
        return to_dict(value.model_dump(mode="json"))

    if hasattr(value, "dict") and callable(value.dict):
        return to_dict(value.dict())

    if hasattr(value, "items") and callable(value.items):
        try:
            return to_dict(dict(value.items()))
        except Exception:
            pass

    return value


def get_amount(value):
    """Convert a number or SDK money object into a float."""
    value = to_dict(value)

    if isinstance(value, dict):
        value = value.get("value")

    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def find_amount_in_payload(payload):
    """
    Find a likely monetary amount in a cash activity.

    The actual API response should be checked to confirm which field
    represents the amount in USD.
    """
    payload = to_dict(payload)

    if isinstance(payload, dict):
        amount_keys = (
            "amountUsd",
            "amountUSD",
            "amount_usd",
            "cashAmount",
            "cash_amount",
            "amount",
            "value",
        )

        for key in amount_keys:
            if key not in payload or payload[key] is None:
                continue

            amount = get_amount(payload[key])

            if amount is not None:
                return amount

        for value in payload.values():
            amount = find_amount_in_payload(value)

            if amount is not None:
                return amount

    elif isinstance(payload, list):
        for item in payload:
            amount = find_amount_in_payload(item)

            if amount is not None:
                return amount

    return None


# --------------------------------------------------
# Trade normalization
# --------------------------------------------------

def normalize_trade(activity):
    trade = activity.get("trade") or {}
    execution = trade.get("aggressorExecution") or {}
    order = execution.get("order") or {}
    metadata = order.get("marketMetadata") or {}

    market_slug = (
        order.get("marketSlug")
        or metadata.get("slug")
    )

    return {
        "activity_type": "TRADE",
        "activity_id": trade.get("id"),
        "timestamp": (
            execution.get("transactTime")
            or order.get("lastTransactTime")
            or order.get("createTime")
        ),
        "market_slug": market_slug,
        "market_title": metadata.get("title") or None,
        "outcome": metadata.get("outcome") or None,
        "side": order.get("side"),
        "action": order.get("action"),
        "outcome_side": order.get("outcomeSide"),
        "status": order.get("state"),
        "price": get_amount(execution.get("lastPx")),
        "quantity": get_amount(execution.get("lastShares")),
        "order_average_price": get_amount(order.get("avgPx")),
        "commission": get_amount(
            execution.get("commissionNotionalCollected")
        ),
        "combo_legs": [],
    }


# --------------------------------------------------
# Position resolution normalization
# --------------------------------------------------

def normalize_resolution(activity):
    resolution = activity.get("positionResolution") or {}

    before = resolution.get("beforePosition") or {}
    after = resolution.get("afterPosition") or {}
    market = resolution.get("market") or {}

    metadata = (
        after.get("marketMetadata")
        or before.get("marketMetadata")
        or {}
    )

    legs = resolution.get("comboLegDetails") or []
    leg_summaries = []
    leg_titles = []

    for leg in legs:
        settlement = leg.get("settlement") or {}

        leg_summaries.append({
            "title": leg.get("title"),
            "outcome": leg.get("outcome"),
            "state": leg.get("state"),
            "event_start_time": leg.get("eventStartTime"),
            "settlement_price": get_amount(
                settlement.get("settlementPrice")
            ),
            "settlement_time": settlement.get("settlementSetTime"),
        })

        if leg.get("title"):
            leg_titles.append(leg["title"])

    market_title = metadata.get("title") or None

    if not market_title and leg_titles:
        market_title = " / ".join(leg_titles)

    quantity = after.get("qtySoldDecimal")

    if quantity is None:
        quantity = after.get("qtySold")

    position_before = before.get("netPositionDecimal")

    if position_before is None:
        position_before = before.get("netPosition")

    position_after = after.get("netPositionDecimal")

    if position_after is None:
        position_after = after.get("netPosition")

    activity_id = resolution.get("tradeId") or (
        f"{resolution.get('marketSlug', market.get('slug', 'unknown'))}:"
        f"{resolution.get('updateTime', '')}:"
        f"{resolution.get('side', '')}"
    )

    return {
        "activity_type": "POSITION_RESOLUTION",
        "activity_id": activity_id,
        "timestamp": (
            resolution.get("updateTime")
            or after.get("updateTime")
        ),
        "market_slug": (
            resolution.get("marketSlug")
            or market.get("slug")
        ),
        "market_title": market_title,
        "outcome": metadata.get("outcome") or None,
        "side": resolution.get("side"),
        "action": None,
        "outcome_side": None,
        "status": market.get("status"),
        "price": None,
        "quantity": get_amount(quantity),
        "cost": get_amount(before.get("cost")),
        "commission": get_amount(after.get("fees")),
        "realized_pnl": get_amount(after.get("realized")),
        "position_before": get_amount(position_before),
        "position_after": get_amount(position_after),
        "cash_value_after": get_amount(after.get("cashValue")),
        "combo_legs": leg_summaries,
    }


# --------------------------------------------------
# Deposit and withdrawal normalization
# --------------------------------------------------

def normalize_cash_activity(activity):
    """
    Normalize deposit, advanced-deposit, and withdrawal records.

    The amount field is best-effort until confirmed against an actual
    sanitized cash activity returned by the API.
    """
    activity = to_dict(activity)

    activity_type = activity.get("type")

    payload_keys = {
        "ACTIVITY_TYPE_ACCOUNT_DEPOSIT": (
            "accountDeposit",
            "deposit",
        ),
        "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT": (
            "accountAdvancedDeposit",
            "advancedDeposit",
        ),
        "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL": (
            "accountWithdrawal",
            "withdrawal",
        ),
    }

    payload = {}

    for key in payload_keys.get(activity_type, ()):
        candidate = activity.get(key)

        if isinstance(candidate, dict):
            payload = candidate
            break

    # Some API responses may place the amount directly on the activity.
    amount = find_amount_in_payload(payload)

    if amount is None:
        amount = find_amount_in_payload(activity)

    return {
        "activity_type": activity_type,
        "activity_id": (
            payload.get("id")
            or activity.get("id")
            or activity.get("activityId")
        ),
        "timestamp": (
            payload.get("timestamp")
            or payload.get("createTime")
            or payload.get("updateTime")
            or activity.get("time")
            or activity.get("timestamp")
            or activity.get("createTime")
        ),
        "amount": amount,
        "status": (
            payload.get("status")
            or activity.get("status")
        ),
    }


# --------------------------------------------------
# Activity normalization dispatcher
# --------------------------------------------------

def normalize_activity(activity):
    activity = to_dict(activity)

    if not isinstance(activity, dict):
        return None

    activity_type = activity.get("type")

    if activity_type == "ACTIVITY_TYPE_TRADE":
        return normalize_trade(activity)

    if activity_type == "ACTIVITY_TYPE_POSITION_RESOLUTION":
        return normalize_resolution(activity)

    if activity_type in CASH_ACTIVITY_TYPES:
        return normalize_cash_activity(activity)

    return None


# --------------------------------------------------
# API response helpers
# --------------------------------------------------

def extract_activities(response):
    """Extract the activities list from the SDK response."""
    response = to_dict(response)

    if isinstance(response, list):
        return response

    if isinstance(response, dict):
        activities = response.get("activities")

        if isinstance(activities, list):
            return activities

        data = response.get("data")

        if isinstance(data, list):
            return data

        if isinstance(data, dict):
            activities = data.get("activities")

            if isinstance(activities, list):
                return activities

    raise ValueError(
        "Could not find an activities list in the API response. "
        "The Polymarket SDK response format may have changed."
    )


def get_response_value(response, key, default=None):
    """Read a field from dict-like SDK response objects."""
    response_dict = to_dict(response)

    if isinstance(response_dict, dict):
        return response_dict.get(key, default)

    return getattr(response, key, default)


# --------------------------------------------------
# Paginated API collection
# --------------------------------------------------

def fetch_all_activities(client, limit=PAGE_SIZE):
    """
    Fetch all available activity pages using the SDK cursor.
    """
    all_activities = []
    cursor = None
    seen_cursors = set()
    page = 0

    while page < MAX_PAGES:
        params = {
            "limit": limit,
            "sortOrder": "SORT_ORDER_DESCENDING",
            "types": REQUESTED_ACTIVITY_TYPES,
        }

        if cursor:
            params["cursor"] = cursor

        response = client.portfolio.activities(params=params)

        activities = extract_activities(response)
        next_cursor = get_response_value(response, "nextCursor")
        eof = bool(get_response_value(response, "eof", False))

        page += 1
        all_activities.extend(activities)

        print(
            f"Page {page}: received {len(activities)} activities "
            f"(raw total: {len(all_activities)})"
        )

        if eof or not next_cursor:
            break

        if next_cursor == cursor or next_cursor in seen_cursors:
            print(
                "Stopping pagination because the API repeated a cursor."
            )
            break

        seen_cursors.add(next_cursor)
        cursor = next_cursor

    else:
        print(
            f"WARNING: reached MAX_PAGES={MAX_PAGES}; "
            "stopping pagination."
        )

    return all_activities


# --------------------------------------------------
# Save normalized data
# --------------------------------------------------

def save_normalized(activities):
    normalized = []

    for activity in activities:
        record = normalize_activity(activity)

        if record is not None:
            normalized.append(record)

    # Deduplicate records.
    unique_records = {}

    for record in normalized:
        activity_id = record.get("activity_id")

        if activity_id is not None:
            key = (
                record.get("activity_type"),
                str(activity_id),
            )
        else:
            key = (
                record.get("activity_type"),
                json.dumps(
                    record,
                    sort_keys=True,
                    ensure_ascii=False,
                ),
            )

        unique_records[key] = record

    normalized = list(unique_records.values())

    # Sort oldest to newest.
    normalized.sort(
        key=lambda item: str(item.get("timestamp") or "")
    )

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(
        json.dumps(
            normalized,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    trade_count = sum(
        item["activity_type"] == "TRADE"
        for item in normalized
    )

    resolution_count = sum(
        item["activity_type"] == "POSITION_RESOLUTION"
        for item in normalized
    )

    deposit_count = sum(
        item["activity_type"] in {
            "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
            "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
        }
        for item in normalized
    )

    withdrawal_count = sum(
        item["activity_type"] == "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL"
        for item in normalized
    )

    cash_records_without_amount = [
        item
        for item in normalized
        if item.get("activity_type") in CASH_ACTIVITY_TYPES
        and item.get("amount") is None
    ]

    print("\nCollection complete")
    print(f"Activities received across pages: {len(activities)}")
    print(f"Unique normalized records: {len(normalized)}")
    print(f"Trades: {trade_count}")
    print(f"Position resolutions: {resolution_count}")
    print(f"Deposits: {deposit_count}")
    print(f"Withdrawals: {withdrawal_count}")

    if cash_records_without_amount:
        print(
            "WARNING: "
            f"{len(cash_records_without_amount)} deposit/withdrawal "
            "records have no recognized amount."
        )
        print(
            "Inspect a sanitized cash activity payload and update "
            "normalize_cash_activity() to match its actual fields."
        )

    print(f"Saved to: {OUTPUT_FILE.resolve()}")

    if normalized:
        print(
            "Oldest timestamp in saved data: "
            f"{normalized[0].get('timestamp')}"
        )
        print(
            "Newest timestamp in saved data: "
            f"{normalized[-1].get('timestamp')}"
        )

    return normalized


# --------------------------------------------------
# API connection
# --------------------------------------------------

def fetch_activities():
    if not KEY_ID or not SECRET_KEY:
        raise RuntimeError(
            "API credentials are missing. Check the root .env file "
            "for POLYMARKET_KEY_ID and POLYMARKET_SECRET_KEY. "
            "Do not paste your secret key into chat or source code."
        )

    client = PolymarketUS(
        key_id=KEY_ID,
        secret_key=SECRET_KEY,
    )

    try:
        print("Connecting to Polymarket US API...")
        activities = fetch_all_activities(client)
        return save_normalized(activities)
    finally:
        client.close()


if __name__ == "__main__":
    try:
        fetch_activities()
    except Exception as error:
        print(f"Activity collection failed: {error}")
        raise