const money = value => value == null ? "—" : new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(value);
let allActivities = [];

async function refresh() {
  const response = await fetch("/api/summary");
  const data = await response.json();
  document.querySelector("#deposits").textContent = money(data.deposits);
  document.querySelector("#withdrawals").textContent = money(data.withdrawals);
  document.querySelector("#cashflow").textContent = money(data.net_cash_flow);
  document.querySelector("#pnl").textContent = money(data.realized_pnl);
  document.querySelector("#balance").textContent = money(data.balance);
  document.querySelector("#count").textContent = data.activity_count;
  document.querySelector("#cashflow").className = data.net_cash_flow >= 0 ? "positive" : "negative";
  allActivities = data.activities || [];
  renderRows();
}

function renderRows() {
  const term = document.querySelector("#search").value.toLowerCase();
  const filtered = allActivities.filter(a => `${a.date} ${a.type} ${a.description}`.toLowerCase().includes(term));
  const tbody = document.querySelector("#rows");
  tbody.replaceChildren();
  if (!filtered.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4; td.className = "empty"; td.textContent = "No matching activity records.";
    tr.appendChild(td); tbody.appendChild(tr); return;
  }
  for (const item of filtered) {
    const tr = document.createElement("tr");
    for (const [value, cls] of [[item.date || "—",""],[item.type || "Activity",""],[item.description || "—",""],[money(item.amount ?? 0),"number"]]) {
      const td = document.createElement("td");
      td.textContent = value; if (cls) td.className = cls;
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#search").addEventListener("input", renderRows);
document.querySelector("#import").addEventListener("click", async () => {
  const status = document.querySelector("#importStatus");
  try {
    const payload = JSON.parse(document.querySelector("#jsonInput").value);
    const response = await fetch("/api/import", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Import failed");
    status.textContent = `Imported ${result.activity_count} activity records.`;
    await refresh();
  } catch (error) {
    status.textContent = `Error: ${error.message}`;
  }
});
refresh().catch(err => console.error("Could not load PolyTrack data", err));
