import csv
import io
import json
from pathlib import Path

from flask import Flask, jsonify, render_template, Response, request

app = Flask(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "data" / "activities_normalized.json"


# --------------------------------------------------
# Load activities
# --------------------------------------------------

def load_activities():
    if not DATA_FILE.exists():
        return []

    with DATA_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data, list):
        raise ValueError("Activity JSON must contain a list.")

    return [item for item in data if isinstance(item, dict)]


# --------------------------------------------------
# Helpers
# --------------------------------------------------

def number(value):
    try:
        return float(value) if value is not None else None
    except (ValueError, TypeError):
        return None


def money_sum(items, field):
    """Sum valid numeric values for a field."""
    values = [
        number(item.get(field))
        for item in items
    ]

    return sum(value for value in values if value is not None)


# --------------------------------------------------
# Summary calculations
# --------------------------------------------------

def get_summary(activities):
    trades = [
        item for item in activities
        if item.get("activity_type") == "TRADE"
    ]

    resolutions = [
        item for item in activities
        if item.get("activity_type") == "POSITION_RESOLUTION"
    ]

    # Position-resolution realized P&L
    pnl_values = [
        number(item.get("realized_pnl"))
        for item in resolutions
    ]

    pnl_values = [
        value for value in pnl_values
        if value is not None
    ]

    # Recorded commissions
    commissions = [
        number(item.get("commission"))
        for item in activities
    ]

    commissions = [
        value for value in commissions
        if value is not None
    ]

    total_realized_pnl = sum(pnl_values)
    total_commissions = sum(commissions)

    # Wins and losses are based on resolution records with nonzero P&L.
    wins = sum(value > 0 for value in pnl_values)
    losses = sum(value < 0 for value in pnl_values)
    decided = wins + losses

    # Deposits include regular and advanced deposits.
    deposit_types = {
        "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
        "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
    }

    deposits = [
        item for item in activities
        if item.get("activity_type") in deposit_types
    ]

    withdrawals = [
        item for item in activities
        if item.get("activity_type")
        == "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL"
    ]

    total_deposited = money_sum(deposits, "amount")
    total_withdrawn = money_sum(withdrawals, "amount")

    # Sum positive realized P&L only.
    # This is not total payouts or unrealized profit.
    total_money_won = sum(
        value for value in pnl_values
        if value > 0
    )

    # Count cash activities whose amount was not recognized.
    missing_deposit_amounts = sum(
        item.get("amount") is None
        for item in deposits
    )

    missing_withdrawal_amounts = sum(
        item.get("amount") is None
        for item in withdrawals
    )

    return {
        # Activity totals
        "total_records": len(activities),
        "trade_count": len(trades),
        "resolution_count": len(resolutions),

        # P&L
        "realized_pnl": round(total_realized_pnl, 2),
        "recorded_commissions": round(total_commissions, 2),
        "pnl_after_recorded_commissions": round(
            total_realized_pnl - total_commissions, 2
        ),

        # Wins and losses
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round(
            wins / decided * 100, 2
        ) if decided else None,

        # Cash flow
        "total_deposited": round(total_deposited, 2),
        "total_withdrawn": round(total_withdrawn, 2),
        "net_cash_flow": round(
            total_deposited - total_withdrawn, 2
        ),

        # Positive realized P&L only
        "total_money_won": round(total_money_won, 2),

        # Data-quality indicators
        "deposit_count": len(deposits),
        "withdrawal_count": len(withdrawals),
        "deposits_missing_amount": missing_deposit_amounts,
        "withdrawals_missing_amount": missing_withdrawal_amounts,
    }


# --------------------------------------------------
# Dashboard
# --------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


# --------------------------------------------------
# Health check
# --------------------------------------------------

@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "PolyTrack",
    })


# --------------------------------------------------
# Trading summary API
# --------------------------------------------------

@app.get("/api/trading/summary")
def trading_summary():
    try:
        activities = load_activities()
        return jsonify(get_summary(activities))

    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return jsonify({"error": str(exc)}), 500


# --------------------------------------------------
# Trading activities API
# --------------------------------------------------

@app.get("/api/trading/activities")
def trading_activities():
    try:
        activities = load_activities()

    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return jsonify({"error": str(exc)}), 500

    activity_type = request.args.get("type", "").upper()

    if activity_type:
        allowed_types = {
            "TRADE",
            "POSITION_RESOLUTION",
            "ACTIVITY_TYPE_ACCOUNT_DEPOSIT",
            "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT",
            "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL",
        }

        if activity_type not in allowed_types:
            return jsonify({
                "error": (
                    "Unsupported type. Use TRADE, "
                    "POSITION_RESOLUTION, or a supported "
                    "account deposit/withdrawal activity type."
                )
            }), 400

        activities = [
            item for item in activities
            if item.get("activity_type") == activity_type
        ]

    activities.sort(
        key=lambda item: str(item.get("timestamp") or ""),
        reverse=True,
    )

    try:
        limit = int(request.args.get("limit", 500))
    except ValueError:
        return jsonify({
            "error": "limit must be an integer"
        }), 400

    limit = max(1, min(limit, 5000))

    return jsonify({
        "count": len(activities),
        "returned": min(len(activities), limit),
        "activities": activities[:limit],
    })


# --------------------------------------------------
# CSV export
# --------------------------------------------------

@app.get("/api/trading/export.csv")
def export_trading_csv():
    try:
        activities = load_activities()
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return jsonify({"error": str(exc)}), 500

    output = io.StringIO()

    fields = [
        "timestamp",
        "activity_type",
        "activity_id",
        "market_title",
        "market_slug",
        "outcome",
        "side",
        "action",
        "price",
        "quantity",
        "amount",
        "commission",
        "realized_pnl",
        "status",
    ]

    writer = csv.DictWriter(
        output,
        fieldnames=fields,
        extrasaction="ignore",
    )

    writer.writeheader()

    for item in activities:
        writer.writerow({
            field: item.get(field)
            for field in fields
        })

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=polytrack_trading_history.csv"
        },
    )


# --------------------------------------------------
# Start application
# --------------------------------------------------

if __name__ == "__main__":
    print("\nPolyTrack registered routes:")
    print(app.url_map)

    app.run(
        host="127.0.0.1",
        port=5050,
        debug=True,
    )