# Start, pause, and check the paper trader

The dashboard and day-trader worker are separate processes. Stop both when you are not paper trading to avoid using local CPU, memory, and market-data requests.

## Start the dashboard

Open PowerShell in the Trade-Bot folder and run:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

Leave that window open. The local dashboard is available at `http://127.0.0.1:8000`.

## Start the paper day trader

Open a second PowerShell window in the same folder and run:

```powershell
.\.venv312\Scripts\python.exe -m backend.day_trader
```

It watches every symbol in `SYMBOL_WHITELIST`, allows one paper position per symbol, and operates only during US regular market hours. The dashboard status panel confirms which symbols it is watching.

## Stop everything

If you started the commands in visible PowerShell windows, press `Ctrl+C` in each window.

If they were started in the background, use this command in PowerShell:

```powershell
$targets = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
  Where-Object { $_.CommandLine -like '*Trade-Bot*' -and ($_.CommandLine -match 'backend\.day_trader|uvicorn') }
$targets | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

This stops only the Trade-Bot dashboard and paper day-trader processes. If Windows reports access denied, reopen PowerShell as Administrator and run the command again.

## Check whether it is running

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health | Select-Object -ExpandProperty Content
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/system | Select-Object -ExpandProperty Content
```

The first command should return `healthy`; the second shows the day-trader state, symbols, and market time.

## Optional: private Tailscale access

After starting the dashboard, make it available privately to your Tailnet:

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```

Open the private HTTPS address shown by the status command from a signed-in Tailscale device. To disable only remote access later:

```powershell
tailscale serve reset
```

Do not use Tailscale Funnel for this dashboard.

## Reset for a new paper-trading session

A reset removes only simulated runtime data. It preserves `.env`, your watchlist, strategy settings, and the application code.

1. Stop the dashboard and paper day-trader using the commands above.
2. Remove the paper database and worker state:

```powershell
$resetFiles = @(
  'database\trading.db',
  'database\auto_trader_state.json',
  'database\day_trader_state.json',
  'database\runtime_status.json',
  'database\backtest_results.json'
)
$resetFiles | ForEach-Object {
  if (Test-Path -LiteralPath $_) { Remove-Item -LiteralPath $_ -Force }
}
```

3. Start the dashboard and paper day trader again when you are ready. The application recreates a clean database automatically.

This cannot recover deleted paper trades or alerts, so reset only when you no longer need the prior session's records.