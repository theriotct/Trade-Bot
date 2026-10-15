const byId = id => document.getElementById(id);
const safe = value => String(value ?? "").replace(/[&<>\'"]/g, character => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
}[character]));
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const strategyLabels = {
  trend: "Trend 50/200", donchian: "Donchian breakout", macd: "MACD",
  bollinger: "Bollinger reversion", rsi: "RSI reversion",
  volatility_breakout: "Volatility breakout", regression: "Regression slope"
};
const strategyName = value => strategyLabels[value] || value;
const pnl = value => `<span class="${Number(value) >= 0 ? "positive" : "negative"}">${money.format(Number(value) || 0)}</span>`;
let symbols = [];
let strategies = [];
let plans = [];
let selectedSymbols = new Set();

function nextWeekday() {
  const todayParts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", year: "numeric", month: "numeric", day: "numeric"
  }).formatToParts(new Date());
  const part = name => Number(todayParts.find(item => item.type === name).value);
  const date = new Date(Date.UTC(part("year"), part("month") - 1, part("day") + 1));
  while (date.getUTCDay() === 0 || date.getUTCDay() === 6) date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function todayEastern() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit"
  }).formatToParts(new Date());
  const part = name => parts.find(item => item.type === name).value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function renderSymbols() {
  const query = byId("symbol-filter").value.trim().toUpperCase();
  byId("symbol-options").innerHTML = symbols.map(symbol => `
    <label class="symbol-option" data-symbol-option="${safe(symbol)}">
      <input type="checkbox" value="${safe(symbol)}" ${selectedSymbols.has(symbol) ? "checked" : ""}>
      <span>${safe(symbol)}</span>
    </label>`).join("");
  byId("symbol-options").querySelectorAll("input").forEach(input => {
    input.closest(".symbol-option").hidden = query && !input.value.includes(query);
    input.addEventListener("change", () => {
      if (input.checked) selectedSymbols.add(input.value);
      else selectedSymbols.delete(input.value);
      updatePreview();
    });
  });
  const visible = [...byId("symbol-options").querySelectorAll(".symbol-option")].filter(item => !item.hidden);
  byId("select-filtered").disabled = !visible.length;
  updatePreview();
}

function updatePreview() {
  const chosenStrategy = byId("test-strategy").value;
  const perSymbol = chosenStrategy === "all" ? strategies.filter(item => item !== "all").length : 1;
  const runs = selectedSymbols.size * perSymbol;
  const amount = Number(byId("starting-amount").value) || 0;
  byId("run-preview").textContent = `${runs} independent run${runs === 1 ? "" : "s"} · ${selectedSymbols.size} symbol${selectedSymbols.size === 1 ? "" : "s"}`;
  byId("capital-preview").textContent = `${money.format(amount * runs)} virtual starting capital`;
  byId("symbol-selection-summary").textContent = selectedSymbols.size
    ? `${selectedSymbols.size} selected · up to 100 symbols`
    : "Choose at least one configured symbol.";
}

function renderReport(plan) {
  const report = plan.report;
  if (!report) return "";
  const pairs = report.pairs || [];
  const rows = pairs.map(pair => {
    const percent = Number(pair.starting_amount) ? (Number(pair.realized_pnl) / Number(pair.starting_amount) * 100) : 0;
    const trades = pair.trades || [];
    return `<tr>
      <td>${safe(pair.symbol)}</td><td>${safe(strategyName(pair.strategy))}</td>
      <td>${pair.closed_trades} (${pair.wins}W / ${pair.losses}L${pair.flats ? ` / ${pair.flats} flat` : ""})</td>
      <td>${pnl(pair.realized_pnl)}</td><td>${percent.toFixed(2)}%</td>
      <td>${pair.stopped ? "Loss limit" : "—"}${pair.skipped_entries ? ` · ${pair.skipped_entries} entry skipped` : ""}</td>
      <td>${trades.length ? `<details class="plan-trades"><summary>Trade log (${trades.length})</summary><div class="table-wrap"><table><thead><tr><th>Entry</th><th>Exit</th><th>Entry price</th><th>Exit price</th><th>P/L</th><th>Entry signal</th><th>Exit reason</th></tr></thead><tbody>${trades.map(trade => `<tr><td>${safe(trade.entry_time || "—")}</td><td>${safe(trade.exit_time || "—")}</td><td>${money.format(Number(trade.entry_price) || 0)}</td><td>${money.format(Number(trade.exit_price) || 0)}</td><td>${pnl(trade.pnl)}</td><td>${safe(trade.entry_reason || "—")}</td><td>${safe(trade.reason)}</td></tr>`).join("")}</tbody></table></div></details>` : "No trades"}</td>
    </tr>`;
  }).join("");
  return `<details class="plan-report" ${plan.status === "completed" ? "" : ""}>
    <summary>${plan.status === "completed" ? "Open end-of-day report" : "View run details"}</summary>
    <div class="plan-report-summary"><p>${safe(report.summary || "")}</p>${report.data_source ? `<span>Data: ${safe(report.data_source)}</span>` : ""}${report.realized_pnl !== undefined ? `<span>Starting capital: ${money.format(report.total_starting_amount)}</span><span>Realized P/L: ${pnl(report.realized_pnl)}</span><span>Return: ${Number(report.return_pct || 0).toFixed(2)}%</span><span>${report.closed_trades} closes · ${report.wins} wins · ${report.losses} losses</span>${report.skipped_entries ? `<span>${report.skipped_entries} entry signals skipped at position cap</span>` : ""}` : ""}</div>
    <div class="plan-report-table"><table><thead><tr><th>Symbol</th><th>Strategy</th><th>Closed outcomes</th><th>Realized P/L</th><th>Return</th><th>Risk / entries</th><th>Trade details</th></tr></thead><tbody>${rows}</tbody></table></div>
  </details>`;
}

function renderPlans() {
  const target = byId("one-day-plans");
  if (!plans.length) {
    target.innerHTML = '<p class="empty">No runs queued yet. Build a test above to get started.</p>';
    return;
  }
  target.innerHTML = plans.map(plan => {
    const allStrategies = plan.strategies.length > 1;
    const strategyText = allStrategies ? `All strategies (${plan.strategies.length})` : strategyName(plan.strategies[0]);
    const modeLabel = plan.mode === "historical_backtest" ? " · Historical backtest" : "";
    const title = `${plan.target_date} · ${strategyText}${modeLabel}`;
    const meta = `${plan.symbols.join(", ")} · ${money.format(plan.starting_amount)} per symbol–strategy run · ${money.format(plan.loss_limit)} pair loss limit · up to ${plan.max_open_positions} open at once`;
    const progress = plan.progress
      ? `${plan.progress.closed_trades} closed · ${plan.progress.open_positions} open · ${plan.progress.stopped_pairs} stopped · ${pnl(plan.progress.realized_pnl)} realized`
      : plan.status === "queued" ? "Waiting for the scheduled session." : "";
    return `<article class="one-day-plan">
      <div class="one-day-plan-head"><div><div class="one-day-plan-title"><strong>${safe(title)}</strong><span class="plan-status ${safe(plan.status)}">${safe(plan.status)}</span></div><div class="one-day-plan-meta">${safe(meta)}</div></div>
        ${["queued", "running"].includes(plan.status) ? `<button class="plan-cancel" type="button" data-cancel-plan="${safe(plan.id)}" data-status="${safe(plan.status)}">${plan.status === "running" ? "Stop run" : "Cancel"}</button>` : ""}
      </div>
      ${progress ? `<div class="plan-progress">${progress}</div>` : ""}
      ${renderReport(plan)}
    </article>`;
  }).join("");
  target.querySelectorAll("[data-cancel-plan]").forEach(button => button.addEventListener("click", async () => {
    if (button.dataset.status === "running" && !window.confirm("Stop this test and close its simulated positions at their latest recorded prices?")) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/one-day-lab/${encodeURIComponent(button.dataset.cancelPlan)}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error((await response.json()).detail || "Could not cancel this run.");
      await load();
    } catch (error) {
      button.disabled = false;
      setMessage(error.message, true);
    }
  }));
}

function setMessage(message, error = false) {
  const element = byId("form-message");
  element.textContent = message;
  element.className = `form-message${message ? error ? " error" : " success" : ""}`;
}

async function load() {
  try {
    const response = await fetch("/api/one-day-lab");
    if (!response.ok) throw new Error("Unable to load the one-day test queue.");
    const data = await response.json();
    const oldSymbols = symbols.join(",");
    symbols = data.symbols || [];
    strategies = data.strategies || [];
    if (oldSymbols !== symbols.join(",")) renderSymbols();
    const strategyOptions = strategies.map(strategy => `<option value="${safe(strategy)}">${safe(strategy === "all" ? "All strategies" : strategyName(strategy))}</option>`).join("");
    if (byId("test-strategy").innerHTML !== strategyOptions) byId("test-strategy").innerHTML = strategyOptions;
    byId("one-day-status").textContent = "PAPER • Online";
    byId("one-day-status").className = "status online";
    plans = data.plans || [];
    renderPlans();
    updatePreview();
  } catch (error) {
    byId("one-day-status").textContent = "Service unavailable";
    byId("one-day-status").className = "status offline";
    setMessage(error.message, true);
  }
}

byId("test-date").value = nextWeekday();
byId("symbol-filter").addEventListener("input", renderSymbols);
byId("test-strategy").addEventListener("change", updatePreview);
byId("starting-amount").addEventListener("input", updatePreview);
byId("select-filtered").addEventListener("click", () => {
  byId("symbol-options").querySelectorAll(".symbol-option:not([hidden]) input").forEach(input => selectedSymbols.add(input.value));
  renderSymbols();
});
byId("clear-symbols").addEventListener("click", () => {
  selectedSymbols.clear();
  renderSymbols();
});
byId("refresh-plans").addEventListener("click", load);
function buildPayload() {
  const strategy = byId("test-strategy").value;
  return {
    target_date: byId("test-date").value,
    symbols: [...selectedSymbols],
    strategy,
    loss_limit: Number(byId("loss-limit").value),
    starting_amount: Number(byId("starting-amount").value),
    max_open_positions: Number(byId("max-open-positions").value)
  };
}

async function submitRun(url, button, messageText, successText) {
  const payload = buildPayload();
  button.disabled = true;
  byId("form-message").textContent = messageText;
  byId("form-message").className = "form-message";
  try {
    const response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok) {
      const detail = result.detail;
      const errorText = typeof detail === "string" ? detail
        : Array.isArray(detail) ? detail.map(item => item.msg).join("; ")
          : "Could not start the test.";
      throw new Error(errorText);
    }
    if (url.endsWith("/backtest")) {
      plans = [result, ...plans.filter(plan => plan.id !== result.id)].slice(0, 50);
      renderPlans();
      setMessage(result.status === "completed" ? successText : (result.report?.summary || "The backtest could not complete."), result.status !== "completed");
    } else {
      setMessage(`${successText} ${result.target_date} test with ${result.symbols.length * result.strategies.length} independent runs.`);
      await load();
    }
    byId("one-day-plans").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    button.disabled = false;
  }
}

byId("one-day-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (!selectedSymbols.size) return setMessage("Choose at least one symbol.", true);
  if (selectedSymbols.size > 100) return setMessage("Choose no more than 100 symbols per run.", true);
  await submitRun("/api/one-day-lab/queue", event.submitter, "Queueing paper test…", "Queued");
});

byId("backtest-past-day").addEventListener("click", async event => {
  if (!byId("one-day-form").reportValidity()) return;
  if (!selectedSymbols.size) return setMessage("Choose at least one symbol.", true);
  if (selectedSymbols.size > 20) return setMessage("Historical backtests are limited to 20 symbols to keep Yahoo Finance requests and replay time manageable.", true);
  const today = todayEastern();
  const date = byId("test-date").value;
  const min = new Date(`${today}T00:00:00Z`);
  min.setUTCDate(min.getUTCDate() - 3);
  const oldest = min.toISOString().slice(0, 10);
  if (!date || date < oldest || date >= today) return setMessage("Choose a completed date from the last three calendar days.", true);
  const [year, month, day] = date.split("-").map(Number);
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  if (weekday === 0 || weekday === 6) return setMessage("Choose a weekday with a completed market session.", true);
  await submitRun("/api/one-day-lab/backtest", event.currentTarget, "Fetching recent Yahoo Finance one-minute bars and replaying strategies…", "Historical backtest complete and saved.");
});

load();
setInterval(load, 30000);
