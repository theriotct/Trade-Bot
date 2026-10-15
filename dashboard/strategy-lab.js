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
let currentChartLab = null;
let chartRange = "all";
let selectedWinLossSymbol = "__all__";

function strategyName(strategy) {
  return labels[strategy] || strategy;
}

function renderBarChart(targetId, items, { title, label, detail }) {
  const target = byId(targetId);
  if (!items.length) {
    target.innerHTML = '<p class="chart-empty">No results to chart yet.</p>';
    return;
  }

  const width = 1000;
  const left = 238;
  const right = 84;
  const top = 18;
  const rowHeight = 38;
  const bottom = 43;
  const plotWidth = width - left - right;
  const height = top + items.length * rowHeight + bottom;
  const values = items.map(item => Number(item.pnl) || 0);
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const padding = Math.max((high - low) * 0.09, 1);
  const min = low - padding;
  const max = high + padding;
  const x = value => left + ((value - min) / (max - min)) * plotWidth;
  const zero = x(0);
  const ticks = Array.from({ length: 5 }, (_, index) => min + ((max - min) * index) / 4);
  const grid = ticks.map(value => {
    const tickX = x(value);
    return `<line class="chart-gridline" x1="${tickX}" y1="${top - 5}" x2="${tickX}" y2="${height - bottom + 3}" />
      <text class="chart-tick" x="${tickX}" y="${height - 12}" text-anchor="middle">${safe(money.format(value))}</text>`;
  }).join("");
  const rows = items.map((item, index) => {
    const value = Number(item.pnl) || 0;
    const y = top + index * rowHeight;
    const end = x(value);
    const barX = Math.min(zero, end);
    const barWidth = Math.max(Math.abs(end - zero), 2);
    const valueX = Math.min(Math.max(end + (value >= 0 ? 8 : -8), left + 5), width - 5);
    const valueAnchor = valueX >= width - 8 ? "end" : value >= 0 ? "start" : "end";
    const rowTitle = `${label(item)}: ${money.format(value)}${detail ? ` · ${detail(item)}` : ""}`;
    return `<g class="chart-row">
      <title>${safe(rowTitle)}</title>
      <text class="chart-label" x="${left - 14}" y="${y + 14}" text-anchor="end">${safe(label(item))}</text>
      ${detail ? `<text class="chart-detail" x="${left - 14}" y="${y + 29}" text-anchor="end">${safe(detail(item))}</text>` : ""}
      <rect class="chart-bar ${value >= 0 ? "chart-bar-positive" : "chart-bar-negative"}" x="${barX}" y="${y + 7}" width="${barWidth}" height="20" rx="5" />
      <text class="chart-value ${value >= 0 ? "chart-value-positive" : "chart-value-negative"}" x="${valueX}" y="${y + 21}" text-anchor="${valueAnchor}">${safe(money.format(value))}</text>
    </g>`;
  }).join("");

  target.innerHTML = `<svg class="lab-bar-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${safe(title)}">
    <title>${safe(title)}</title>
    <desc>Horizontal bars show positive and negative paper trading profit and loss in US dollars, measured from the zero line.</desc>
    ${grid}<line class="chart-zero" x1="${zero}" y1="${top - 5}" x2="${zero}" y2="${height - bottom + 3}" />
    ${rows}
  </svg>`;
}

function renderWinLossChart(chartLab) {
  const select = byId("win-loss-symbol");
  const target = byId("win-loss-chart");
  const rankings = chartLab.strategy_rankings || {};
  const symbols = Object.keys(rankings).sort();
  if (!symbols.length) {
    select.innerHTML = "";
    target.innerHTML = '<p class="chart-empty">No symbol results for this chart range.</p>';
    return;
  }
  if (selectedWinLossSymbol !== "__all__" && !symbols.includes(selectedWinLossSymbol)) selectedWinLossSymbol = "__all__";
  const options = `<option value="__all__">All · cumulative</option>${symbols.map(symbol => `<option value="${safe(symbol)}">${safe(symbol)}</option>`).join("")}`;
  if (select.innerHTML !== options) select.innerHTML = options;
  select.value = selectedWinLossSymbol;

  const sourceRows = selectedWinLossSymbol === "__all__"
    ? Object.values(rankings).flat()
    : rankings[selectedWinLossSymbol] || [];
  const totals = new Map();
  sourceRows.forEach(row => {
    const total = totals.get(row.strategy) || { strategy: row.strategy, wins: 0, losses: 0, flats: 0 };
    total.wins += Number(row.wins) || 0;
    total.losses += Number(row.losses) || 0;
    total.flats += Number(row.flats) || 0;
    totals.set(row.strategy, total);
  });
  const rows = [...totals.values()].map(row => {
    const wins = Number(row.wins) || 0;
    const losses = Number(row.losses) || 0;
    const flats = Number(row.flats) || 0;
    const outcomes = wins + losses;
    return { strategy: row.strategy, wins, losses, flats, outcomes, rate: outcomes ? wins / outcomes : 0 };
  }).filter(row => row.wins + row.losses + row.flats > 0)
    .sort((a, b) => b.rate - a.rate || b.outcomes - a.outcomes);

  if (!rows.length) {
    const symbolLabel = selectedWinLossSymbol === "__all__" ? "any symbol" : selectedWinLossSymbol;
    target.innerHTML = `<p class="chart-empty">No closed trades for ${safe(symbolLabel)} in this chart range.</p>`;
    return;
  }
  target.innerHTML = `<div class="win-loss-rows">${rows.map(row => {
    const winWidth = row.outcomes ? row.rate * 100 : 0;
    const lossWidth = row.outcomes ? 100 - winWidth : 0;
    const rate = row.outcomes ? `${(row.rate * 100).toFixed(1)}% win rate` : "Flat trades only";
    return `<article class="win-loss-row">
      <div class="win-loss-row-heading"><strong>${safe(strategyName(row.strategy))}</strong><span>${rate} · ${row.wins}W / ${row.losses}L${row.flats ? ` / ${row.flats} flat` : ""}</span></div>
      <div class="win-loss-bar" role="img" aria-label="${safe(strategyName(row.strategy))}: ${row.wins} wins, ${row.losses} losses, ${row.flats} flat trades">
        ${row.wins ? `<span class="win-loss-segment wins" style="width:${winWidth}%"></span>` : ""}
        ${row.losses ? `<span class="win-loss-segment losses" style="width:${lossWidth}%"></span>` : ""}
        ${!row.outcomes ? '<span class="win-loss-segment flats" style="width:100%"></span>' : ""}
      </div>
    </article>`;
  }).join("")}</div>`;
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

function renderSymbols(lab, chartLab = lab) {
  const stocks = chartLab.best_by_symbol || [];
  const rankings = chartLab.strategy_rankings || {};
  const query = byId("symbol-search").value.trim().toLowerCase();
  const visible = stocks.filter(stock => {
    // Every symbol has a row for every enabled strategy, so searching all
    // rankings makes a strategy query match the entire universe. Search the
    // symbol and its top result instead.
    const searchable = [stock.symbol, strategyName(stock.strategy)].join(" ").toLowerCase();
    return searchable.includes(query);
  });

  byId("symbol-count").textContent = (lab.best_by_symbol || []).length;
  byId("symbol-result-count").textContent = query
    ? `${visible.length} of ${stocks.length} symbols`
    : `${stocks.length} symbols`;
  renderBarChart("strategy-chart", chartLab.strategies || [], {
    title: "Total paper profit and loss by strategy",
    label: row => strategyName(row.strategy),
    detail: row => `${row.closed_trades} closed · ${row.open_positions} open`
  });
  renderBarChart("symbol-chart", visible, {
    title: "Best strategy profit and loss by symbol",
    label: row => row.symbol,
    detail: row => strategyName(row.strategy)
  });
  renderWinLossChart(chartLab);

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
      renderSymbols(currentLab, currentChartLab || currentLab);
    });
  });
}

function render(lab) {
  currentLab = lab;
  renderStandings(lab);
  renderSymbols(lab, currentChartLab || lab);
}

function chartRangeQuery() {
  if (chartRange === "all") return "";
  const today = new Date();
  const end = today.toISOString();
  const start = new Date(today);
  start.setHours(0, 0, 0, 0);
  if (chartRange === "7d") start.setDate(start.getDate() - 6);
  return `?${new URLSearchParams({ start: start.toISOString(), end })}`;
}

function updateChartRangeButtons() {
  const labels = { today: "Today", "7d": "Last 7 days", all: "All time" };
  document.querySelectorAll("[data-chart-range]").forEach(button => {
    const selected = button.dataset.chartRange === chartRange;
    button.setAttribute("aria-pressed", String(selected));
  });
  byId("chart-range-summary").textContent = labels[chartRange];
}

async function load() {
  try {
    const rangeQuery = chartRangeQuery();
    const [healthResponse, labResponse, chartResponse] = await Promise.all([
      fetch("/health"), fetch("/api/strategy-lab"),
      rangeQuery ? fetch(`/api/strategy-lab/charts${rangeQuery}`) : Promise.resolve(null)
    ]);
    if (!healthResponse.ok || !labResponse.ok || (chartResponse && !chartResponse.ok)) throw new Error("Service request failed");
    const health = await healthResponse.json();
    const lab = await labResponse.json();
    const chartLab = chartResponse ? await chartResponse.json() : lab;
    currentChartLab = chartLab;
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
  if (currentLab) renderSymbols(currentLab, currentChartLab || currentLab);
});

byId("win-loss-symbol").addEventListener("change", event => {
  selectedWinLossSymbol = event.target.value;
  if (currentChartLab) renderWinLossChart(currentChartLab);
});

document.querySelectorAll("[data-chart-range]").forEach(button => {
  button.addEventListener("click", () => {
    chartRange = button.dataset.chartRange;
    updateChartRangeButtons();
    load();
  });
});
updateChartRangeButtons();

const exportDialog = byId("lab-export-dialog");
const exportStart = byId("export-start");
const exportEnd = byId("export-end");
const localDate = date => {
  const offset = date.getTimezoneOffset() * 60000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
};
const startOfLocalDate = value => new Date(`${value}T00:00:00`).toISOString();
const endOfLocalDate = value => {
  const next = new Date(`${value}T00:00:00`);
  next.setDate(next.getDate() + 1);
  return new Date(next.getTime() - 1).toISOString();
};

function setExportRange(range) {
  const today = new Date();
  const todayText = localDate(today);
  if (range === "all") {
    exportStart.value = "";
    exportEnd.value = "";
    return;
  }
  exportEnd.value = todayText;
  if (range === "today") {
    exportStart.value = todayText;
    return;
  }
  const start = new Date(`${todayText}T00:00:00`);
  start.setDate(start.getDate() - Number(range) + 1);
  exportStart.value = localDate(start);
}

byId("open-lab-export").addEventListener("click", () => {
  setExportRange("today");
  byId("lab-export-message").textContent = "";
  exportDialog.showModal();
});
byId("close-lab-export").addEventListener("click", () => exportDialog.close());
byId("cancel-lab-export").addEventListener("click", () => exportDialog.close());
exportDialog.querySelectorAll("[data-export-range]").forEach(button => {
  button.addEventListener("click", () => setExportRange(button.dataset.exportRange));
});
byId("lab-export-form").addEventListener("submit", event => {
  event.preventDefault();
  const start = exportStart.value;
  const end = exportEnd.value;
  const message = byId("lab-export-message");
  if (start && end && start > end) {
    message.textContent = "The start date must be on or before the end date.";
    return;
  }
  const params = new URLSearchParams();
  if (start) params.set("start", startOfLocalDate(start));
  if (end) params.set("end", endOfLocalDate(end));
  window.location.href = `/api/strategy-lab/export${params.size ? `?${params}` : ""}`;
  exportDialog.close();
});

load();
setInterval(load, 5000);
