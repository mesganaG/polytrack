from flask import Flask, render_template, jsonify, request, send_file
from pathlib import Path
import csv
import io
import json
from datetime import datetime, timezone

app = Flask(__name__)
DATA_DIR = Path(__file__).parent / "data"
ACTIVITY_FILE = DATA_DIR / "activity.json"
BALANCE_FILE = DATA_DIR / "balances.json"

DATA_DIR.mkdir(exist_ok=True)

def load_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default

def amount(item, *keys):
    for key in keys:
        value = item.get(key)
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                pass
    return 0.0

def summarize(activities, balances):
    # Activity schema varies by endpoint. Do not silently classify unknown records.
    deposits = withdrawals = realized_pnl = 0.0
    categorized = []
    for item in activities:
        kind = str(item.get("type") or item.get("activityType") or item.get("kind") or "").lower()
        value = amount(item, "amount", "amountUsd", "value", "usdcAmount")
        pnl = amount(item, "realizedPnl", "realized_pnl", "pnl")
        if "deposit" in kind:
            deposits += abs(value)
            category = "Deposit"
        elif "withdraw" in kind:
            withdrawals += abs(value)
            category = "Withdrawal"
        elif "realiz" in kind or "settle" in kind or "redeem" in kind:
            realized_pnl += pnl if pnl else value
            category = "Trading / settlement"
        else:
            category = item.get("displayType") or item.get("type") or "Activity"
        categorized.append({
            "date": item.get("timestamp") or item.get("createdAt") or item.get("time") or "",
            "type": category,
            "description": item.get("title") or item.get("marketTitle") or item.get("description") or item.get("marketSlug") or "",
            "amount": value,
            "raw": item
        })

    balance_value = None
    if isinstance(balances, dict):
        for key in ("balance", "availableBalance", "currentBalance", "accountBalance", "total"):
            if balances.get(key) is not None:
                balance_value = amount(balances, key)
                break
        if balance_value is None and isinstance(balances.get("balances"), list):
            balance_value = sum(amount(x, "balance", "currentBalance", "availableBalance") for x in balances["balances"])
    elif isinstance(balances, list):
        balance_value = sum(amount(x, "balance", "currentBalance", "availableBalance") for x in balances)

    return {
        "deposits": round(deposits, 2),
        "withdrawals": round(withdrawals, 2),
        "net_cash_flow": round(deposits - withdrawals, 2),
        "realized_pnl": round(realized_pnl, 2),
        "balance": round(balance_value, 2) if balance_value is not None else None,
        "activity_count": len(activities),
        "activities": categorized
    }

@app.get("/")
def index():
    return render_template("index.html")

@app.get("/api/summary")
def api_summary():
    activities = load_json(ACTIVITY_FILE, [])
    balances = load_json(BALANCE_FILE, {})
    if not isinstance(activities, list):
        activities = []
    return jsonify(summarize(activities, balances))

@app.post("/api/import")
def import_data():
    """Import sanitized JSON exported by the user. No credentials are accepted or stored."""
    payload = request.get_json(silent=True) or {}
    activities = payload.get("activities", [])
    balances = payload.get("balances", {})
    if not isinstance(activities, list):
        return jsonify({"error": "'activities' must be a list"}), 400
    ACTIVITY_FILE.write_text(json.dumps(activities, indent=2), encoding="utf-8")
    BALANCE_FILE.write_text(json.dumps(balances, indent=2), encoding="utf-8")
    return jsonify({"ok": True, "activity_count": len(activities)})

@app.get("/api/export.csv")
def export_csv():
    summary = summarize(load_json(ACTIVITY_FILE, []), load_json(BALANCE_FILE, {}))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=["date", "type", "description", "amount"])
    writer.writeheader()
    for item in summary["activities"]:
        writer.writerow({k: item.get(k, "") for k in writer.fieldnames})
    mem = io.BytesIO(out.getvalue().encode("utf-8-sig"))
    mem.seek(0)
    return send_file(mem, mimetype="text/csv", as_attachment=True, download_name="polytrack-activity.csv")

if __name__ == "__main__":
    # Local-only binding: do not expose this dashboard to your network.
    app.run(host="127.0.0.1", port=5050, debug=False)
