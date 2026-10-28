const money = value => value == null || !Number.isFinite(Number(value))
  ? "—"
  : new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(Number(value));
const number = value => value == null || !Number.isFinite(Number(value))
  ? "—"
  : new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(Number(value));
const dateText = value => {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
};
let allActivities = [];
let allTradingActivities = [];

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

async function refresh() {
  const [data, trading] = await Promise.all([
    getJson("/api/summary"),
    getJson("/api/trading/summary")
  ]);
  document.querySelector("#deposits").textContent = money(data.deposits);
  document.querySelector("#withdrawals").textContent = money(data.withdrawals);
  document.querySelector("#cashflow").textContent = money(data.net_cash_flow);
  document.querySelector("#pnl").textContent = money(data.realized_pnl);
  document.querySelector("#balance").textContent = money(data.balance);
  document.querySelector("#count").textContent = data.activity_count ?? 0;
  document.querySelector("#cashflow").className = Number(data.net_cash_flow) >= 0 ? "positive" : "negative";
  allActivities = data.activities || [];
  renderRows();

  document.querySelector("#tradingPnl").textContent = money(trading.realized_pnl);
  document.querySelector("#commissions").textContent = money(trading.commissions);
  document.querySelector("#netTradingPnl").textContent = money(trading.realized_pnl_less_recorded_trade_commissions);
  document.querySelector("#resolutions").textContent = trading.resolution_count ?? 0;
  document.querySelector("#winRate").textContent = trading.win_rate == null ? "—" : `${number(trading.win_rate)}%`;
  document.querySelector("#tradeCount").textContent = trading.trade_count ?? 0;
  allTradingActivities = trading.activities || [];
  renderTradingRows();
  document.querySelector("#tradingStatus").textContent =
    `Loaded ${trading.record_count ?? allTradingActivities.length} normalized trading records.`;
}

function renderRows() {
  const term = document.querySelector("#search").value.toLowerCase();
  const filtered = allActivities.filter(a => `${a.date} ${a.type} ${a.description}`.toLowerCase().includes(term));
  const tbody = document.querySelector("#rows");
  tbody.replaceChildren();
  if (!filtered.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.className = "empty";
    td.textContent = "No matching activity records.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const item of filtered) {
    const tr = document.createElement("tr");
    for (const [value, cls] of [[dateText(item.date), ""], [item.type || "Activity", ""], [item.description || "—", ""], [money(item.amount ?? 0), "number"]]) {
      const td = document.createElement("td");
      td.textContent = value;
      if (cls) td.className = cls;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function renderTradingRows() {
  const filter = document.querySelector("#tradingType").value;
  const filtered = allTradingActivities.filter(item => !filter || item.activity_type === filter);
  const tbody = document.querySelector("#tradingRows");
  tbody.replaceChildren();
  if (!filtered.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 8;
    td.className = "empty";
    td.textContent = "No trading records match this filter. Run the collector and check data/activities_normalized.json.";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const item of filtered) {
    const tr = document.createElement("tr");
    const market = [item.market_title, item.outcome, item.market_slug].filter(Boolean);
    const cells = [
      [dateText(item.timestamp), ""],
      [item.activity_type === "POSITION_RESOLUTION" ? "Position resolution" : "Trade", ""],
      [market.join(" · ") || "Market details unavailable", ""],
      [[item.side, item.action, item.status].filter(Boolean).join(" / ") || "—", ""],
      [item.price == null ? "—" : money(item.price), "number"],
      [number(item.quantity), "number"],
      [item.commission == null ? "—" : money(item.commission), "number"],
      [item.realized_pnl == null ? "—" : money(item.realized_pnl), "number"]
    ];
    for (const [value, cls] of cells) {
      const td = document.createElement("td");
      td.textContent = value;
      if (cls) td.className = cls;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

document.querySelector("#refresh").addEventListener("click", async () => {
  const button = document.querySelector("#refresh");
  button.disabled = true;
  try {
    await refresh();
  } catch (error) {
    console.error("Could not refresh PolyTrack", error);
    document.querySelector("#tradingStatus").textContent = `Could not load dashboard data: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});
document.querySelector("#search").addEventListener("input", renderRows);
document.querySelector("#tradingType").addEventListener("change", renderTradingRows);
document.querySelector("#import").addEventListener("click", async () => {
  const status = document.querySelector("#importStatus");
  try {
    const payload = JSON.parse(document.querySelector("#jsonInput").value);
    const response = await fetch("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Import failed");
    status.textContent = `Imported ${result.activity_count} account activity records.`;
    await refresh();
  } catch (error) {
    status.textContent = `Error: ${error.message}`;
  }
});

refresh().catch(error => {
  console.error("Could not load PolyTrack data", error);
  const status = document.querySelector("#tradingStatus");
  if (status) status.textContent = `Could not load dashboard data: ${error.message}`;
});
