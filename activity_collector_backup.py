
import json
from pathlib import Path


OUTPUT_FILE = Path("data/activities_normalized.json")


def amount(obj):
    """Convert a monetary object like {'value': '-9.0398'} to a number."""
    if isinstance(obj, dict):
        obj = obj.get("value")
    try:
        return float(obj) if obj is not None else None
    except (TypeError, ValueError):
        return None


def normalize_activity(activity):
    activity_type = activity.get("type", "")
    trade = activity.get("trade") or {}
    resolution = activity.get("positionResolution") or {}

    if activity_type == "ACTIVITY_TYPE_TRADE":
        execution = trade.get("aggressorExecution") or {}
        order = execution.get("order") or {}
        metadata = order.get("marketMetadata") or {}

        return {
            "activity_type": "TRADE",
            "activity_id": trade.get("id"),
            "timestamp": (
                execution.get("transactTime")
                or order.get("createTime")
            ),
            "market_slug": order.get("marketSlug"),
            "market_title": metadata.get("title") or None,
            "outcome": metadata.get("outcome") or None,
            "side": order.get("side"),
            "action": order.get("action"),
            "status": order.get("state"),
            "price": amount(execution.get("lastPx")),
            "quantity": amount(execution.get("lastShares")),
            "cost": amount(order.get("price")),
            "commission": amount(
                execution.get("commissionNotionalCollected")
            ),
            "realized_pnl": None,
            "combo_legs": [],
        }

    if activity_type == "ACTIVITY_TYPE_POSITION_RESOLUTION":
        before = resolution.get("beforePosition") or {}
        after = resolution.get("afterPosition") or {}
        market = resolution.get("market") or {}
        metadata = after.get("marketMetadata") or {}
        legs = resolution.get("comboLegDetails") or []

        # Resolution P&L is taken from the after-position's realized value.
        pnl = amount(after.get("realized"))

        # Prefer actual leg titles when the market title is empty.
        leg_titles = [
            leg.get("title")
            for leg in legs
            if leg.get("title")
        ]
        title = metadata.get("title") or (
            " / ".join(leg_titles) if leg_titles else None
        )

        return {
            "activity_type": "POSITION_RESOLUTION",
            "activity_id": (
                resolution.get("tradeId")
                or (
                    f"{resolution.get('marketSlug', '')}:"
                    f"{resolution.get('updateTime', '')}:"
                    f"{resolution.get('side', '')}"
                )
            ),
            "timestamp": (
                resolution.get("updateTime")
                or after.get("updateTime")
            ),
            "market_slug": (
                resolution.get("marketSlug")
                or market.get("slug")
            ),
            "market_title": title,
            "outcome": metadata.get("outcome") or None,
            "side": resolution.get("side"),
            "action": None,
            "status": market.get("status"),
            "price": None,
            "quantity": amount(after.get("qtySoldDecimal"))
                or amount(after.get("qtySold")),
            "cost": amount(before.get("cost")),
            "commission": amount(after.get("fees")),
            "realized_pnl": pnl,
            "position_before": amount(before.get("netPositionDecimal"))
                if before.get("netPositionDecimal") is not None
                else amount(before.get("netPosition")),
            "position_after": amount(after.get("netPositionDecimal"))
                if after.get("netPositionDecimal") is not None
                else amount(after.get("netPosition")),
            "cash_value_after": amount(after.get("cashValue")),
            "combo_legs": [
                {
                    "title": leg.get("title"),
                    "outcome": leg.get("outcome"),
                    "state": leg.get("state"),
                    "settlement_price": amount(
                        (leg.get("settlement") or {}).get(
                            "settlementPrice"
                        )
                    ),
                }
                for leg in legs
            ],
        }

    # Keep other activity types identifiable without retaining their full payload.
    return {
        "activity_type": activity_type,
        "activity_id": None,
        "timestamp": None,
        "market_slug": None,
        "market_title": None,
        "outcome": None,
        "realized_pnl": None,
    }


def normalize_response(response):
    activities = (
        response.get("activities", [])
        if isinstance(response, dict)
        else response
    )
    return [
        normalize_activity(item)
        for item in activities
        if isinstance(item, dict)
    ]


def save_normalized(response):
    normalized = normalize_response(response)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(
        json.dumps(normalized, indent=2),
        encoding="utf-8",
    )
    print(f"Saved {len(normalized)} normalized activities to {OUTPUT_FILE}")


# Call save_normalized(api_response) with the response returned by your API.
save_normalized(api_response)