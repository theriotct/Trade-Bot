const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const byId = id => document.getElementById(id);
const safe = value => String(value ?? "").replace(/[&<>\'"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[character]));
const pnl = value => `<span class="${Number(value) >= 0 ? "positive" : "negative"}">${money.format(Number(value) || 0)}</span>`;
const labels = {
  trend: "Trend 50/200",
  donchian: "Donchian breakout",
  macd: "MACD",
  bollinger: "Bollinger reversion",
  rsi: "RSI reversion",
  volatility_breakout: "Volatility breakout",
  regression: "Regression slope"
};

let selectedRankSymbol = null;
let currentLab = null;

function strategyName(strategy) {
  return labels[strategy] || strategy;
}

function renderStandings(lab) {
  const rows = lab.strategies || [];
  const best = rows[0];
  byId("strategy-standings").innerHTML = rows.length
    ? rows.map(row => `<tr>
        <td class="strategy-name">${safe(strategyName(row.strategy))}</td>
        <td>${pnl(row.pnl)}</td>
        <td>${pnl(row.realized_pnl)}</td>
        <td>${row.open_positions}</td>
        <td>${row.closed_trades}</td>
      </tr>`).join("")
    : `<tr><td colspan="5" class="empty">${lab.enabled ? "Waiting for the next completed candle." : "Strategy Lab is switched off."}</td></tr>`;

  byId("strategy-count").textContent = rows.length;
  byId("best-pnl").innerHTML = best ? pnl(best.pnl) : "—";
  byId("best-strategy").textContent = best ? strategyName(best.strategy) : "Waiting for results";
  byId("lab-state-title").textContent = lab.enabled ? "Strategy Lab enabled" : "Strategy Lab disabled";
  byId("lab-state-detail").textContent = lab.enabled ? "Independent results are updating" : "Enable it from Command Center Settings";
  byId("lab-state").classList.toggle("lab-state-disabled", !lab.enabled);
}

function renderSymbols(lab) {
  const stocks = lab.best_by_symbol || [];
  const rankings = lab.strategy_rankings || {};
  const query = byId("symbol-search").value.trim().toLowerCase();
  const visible = stocks.filter(stock => {
    const ranking = rankings[stock.symbol] || [];
    const searchable = [stock.symbol, strategyName(stock.strategy), ...ranking.map(row => strategyName(row.strategy))]
      .join(" ").toLowerCase();
    return searchable.includes(query);
  });

  byId("symbol-count").textContent = stocks.length;
  byId("symbol-result-count").textContent = query
    ? `${visible.length} of ${stocks.length} symbols`
    : `${stocks.length} symbols`;

  if (!stocks.some(stock => stock.symbol === selectedRankSymbol)) selectedRankSymbol = null;
  byId("best-strategies").innerHTML = visible.length
    ? `<div class="symbol-grid">${visible.map(stock => {
        const ranking = rankings[stock.symbol] || [];
        const expanded = selectedRankSymbol === stock.symbol;
        return `<article class="symbol-card ${expanded ? "is-expanded" : ""}">
          <button class="stock-chip ${expanded ? "selected" : ""}" type="button"
            data-rank-symbol="${safe(stock.symbol)}" aria-expanded="${expanded}">
            <span class="symbol-card-heading"><strong>${safe(stock.symbol)}</strong><span class="symbol-best">Top result</span></span>
            <span class="symbol-card-strategy">${safe(strategyName(stock.strategy))}</span>
            <span class="symbol-card-value">${pnl(stock.pnl)}</span>
            <span class="symbol-card-hint">${expanded ? "Hide rankings ↑" : "View all rankings ↓"}</span>
          </button>
          ${expanded ? `<div class="stock-ranking">
            <div class="ranking-heading"><strong>${safe(stock.symbol)}</strong><span>Strategy ranking</span></div>
            ${ranking.length ? `<ol>${ranking.map((entry, index) => `<li class="${index === 0 ? "ranked-first" : ""}">
              <span class="ranking-name"><small>${index + 1}</small>${safe(strategyName(entry.strategy))}${entry.open_position ? '<em>Open</em>' : ""}</span>
              ${pnl(entry.pnl)}
            </li>`).join("")}</ol>` : '<p class="ranking-empty">No strategy results yet.</p>'}
          </div>` : ""}
        </article>`;
      }).join("")}</div>`
    : `<p class="symbol-empty">${query ? "No symbols or strategies match that search." : "No stock results yet."}</p>`;

  byId("best-strategies").querySelectorAll("[data-rank-symbol]").forEach(button => {
    button.addEventListener("click", () => {
      selectedRankSymbol = selectedRankSymbol === button.dataset.rankSymbol ? null : button.dataset.rankSymbol;
      renderSymbols(currentLab);
    });
  });
}

function render(lab) {
  currentLab = lab;
  renderStandings(lab);
  renderSymbols(lab);
}

async function load() {
  try {
    const [healthResponse, labResponse] = await Promise.all([fetch("/health"), fetch("/api/strategy-lab")]);
    if (!healthResponse.ok || !labResponse.ok) throw new Error("Service request failed");
    const [health, lab] = await Promise.all([healthResponse.json(), labResponse.json()]);
    byId("status").textContent = `${health.mode.toUpperCase()} • Online`;
    byId("status").className = "status online";
    byId("updated").textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}`;
    render(lab);
  } catch (_) {
    byId("status").textContent = "Service unavailable";
    byId("status").className = "status offline";
    byId("updated").textContent = "Unable to refresh";
  }
}

byId("symbol-search").addEventListener("input", () => {
  if (currentLab) renderSymbols(currentLab);
});

load();
setInterval(load, 5000);
