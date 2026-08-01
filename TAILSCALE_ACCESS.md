# Private dashboard access with Tailscale

`localhost` works only on the computer running the bot. For another computer or phone, use Tailscale Serve to publish the dashboard privately to your Tailnet—do **not** use Tailscale Funnel for this paper-trading dashboard.

## Start the dashboard locally

Keep the API bound to this computer only:

```powershell
.\.venv312\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

## Make it available to your Tailnet

In a second PowerShell window, run:

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:8000
tailscale serve status
```

Open the private HTTPS address shown by the status command from any signed-in device on your Tailnet. This computer's current Tailscale IP is `100.108.112.68`, but use the HTTPS Serve address rather than opening the app directly by IP and port.

To stop sharing it later:

```powershell
tailscale serve reset
```

## Safety boundary

Tailscale Serve keeps the dashboard inside your Tailnet. Anyone who can access that Tailnet address can view the paper-trading dashboard, so use a private Tailnet and device lock screens. The dashboard has no separate login of its own and must not be exposed to the public internet.
