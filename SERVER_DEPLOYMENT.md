# Server deployment and automatic updates

This guide assumes an Ubuntu server and a GitHub repository. It runs the dashboard/API and the day-trader as separate `systemd` services, so either service is restarted automatically if it crashes.

> Keep this project in paper-trading mode while you set up and test deployment. Do not commit `.env` or credentials.

## About the virtual environment

The `.venv312` folder on this computer does **not** carry its Python libraries to a server. A virtual environment is local to the machine and operating system where it was created.

Create a new server-side virtual environment and install the libraries from `requirements.txt`. Every deployment runs the install command again; it only downloads anything when a requirement changed.

## 1. Install server prerequisites

Run these commands on the Ubuntu server:

```bash
sudo apt update
sudo apt install -y curl git python3 python3-venv python3-pip
curl -fsSL https://tailscale.com/install.sh | sh
sudo adduser --system --group --home /opt/trade-bot tradebot
sudo mkdir -p /opt/trade-bot
sudo chown tradebot:tradebot /opt/trade-bot
```

## 2. Clone the project and create the server virtual environment

Replace `YOUR_GITHUB_NAME` and `YOUR_REPOSITORY`.

```bash
sudo -u tradebot git clone https://github.com/YOUR_GITHUB_NAME/YOUR_REPOSITORY.git /opt/trade-bot
sudo -u tradebot python3 -m venv /opt/trade-bot/.venv
sudo -u tradebot /opt/trade-bot/.venv/bin/python -m pip install --upgrade pip
sudo -u tradebot /opt/trade-bot/.venv/bin/python -m pip install -r /opt/trade-bot/requirements.txt
```

Create the server configuration file. Do not copy the old virtual environment; copy only your settings and secrets into this new `.env` file:

```bash
sudo -u tradebot nano /opt/trade-bot/.env
sudo chmod 600 /opt/trade-bot/.env
sudo chown tradebot:tradebot /opt/trade-bot/.env
```

## 3. Create the API service

```bash
sudo nano /etc/systemd/system/tradebot-api.service
```

Paste:

```ini
[Unit]
Description=Trade Bot dashboard API
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tradebot
Group=tradebot
WorkingDirectory=/opt/trade-bot
EnvironmentFile=/opt/trade-bot/.env
ExecStart=/opt/trade-bot/.venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## 4. Create the trading-worker service

```bash
sudo nano /etc/systemd/system/tradebot-worker.service
```

Paste:

```ini
[Unit]
Description=Trade Bot paper-trading worker
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=tradebot
Group=tradebot
WorkingDirectory=/opt/trade-bot
EnvironmentFile=/opt/trade-bot/.env
ExecStart=/opt/trade-bot/.venv/bin/python -m backend.day_trader
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start both services:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tradebot-api tradebot-worker
sudo systemctl status tradebot-api tradebot-worker --no-pager
curl http://127.0.0.1:8000/health
```

## Tailscale access on port 443

Keep Uvicorn bound to `127.0.0.1:8000`. Tailscale Serve privately proxies the dashboard to your tailnet using HTTPS on port `443`; there is no need to expose port `8000` to the internet or LAN.

Run once on the server and complete the sign-in link it shows:

```bash
sudo tailscale up
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
sudo tailscale serve status
sudo tailscale status --self
```

Open the HTTPS MagicDNS address shown by `tailscale serve status` from a device signed in to your tailnet. Tailscale may prompt you to enable HTTPS certificates for the tailnet the first time you use Serve. Do **not** enable Tailscale Funnel; Serve is private to your tailnet.
## 5. Create a safe deployment script

```bash
sudo nano /opt/trade-bot/deploy.sh
```

Paste:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd /opt/trade-bot
git pull --ff-only origin main
/opt/trade-bot/.venv/bin/python -m pip install -r requirements.txt
/opt/trade-bot/.venv/bin/python -m compileall -q backend
sudo systemctl restart tradebot-api tradebot-worker
curl --fail --retry 10 --retry-delay 2 http://127.0.0.1:8000/health
```

Make it executable and allow the service account to restart only these two services without a password:

```bash
sudo chmod 750 /opt/trade-bot/deploy.sh
sudo chown tradebot:tradebot /opt/trade-bot/deploy.sh
sudo visudo -f /etc/sudoers.d/tradebot-deploy
```

Add this single line in the editor:

```text
tradebot ALL=(root) NOPASSWD: /bin/systemctl restart tradebot-api, /bin/systemctl restart tradebot-worker
```

Test a manual deployment:

```bash
sudo -u tradebot /opt/trade-bot/deploy.sh
sudo journalctl -u tradebot-api -u tradebot-worker -n 100 --no-pager
```

## 6. Set up GitHub Actions auto-deploy

On the server, create a dedicated deployment SSH key:

```bash
sudo -u tradebot ssh-keygen -t ed25519 -f /opt/trade-bot/.ssh_deploy -C "trade-bot-github-deploy" -N ""
sudo -u tradebot cat /opt/trade-bot/.ssh_deploy.pub >> /opt/trade-bot/.ssh/authorized_keys
sudo -u tradebot chmod 700 /opt/trade-bot/.ssh
sudo -u tradebot chmod 600 /opt/trade-bot/.ssh/authorized_keys
sudo -u tradebot cat /opt/trade-bot/.ssh_deploy
```

Copy the private-key output into GitHub repository **Settings → Secrets and variables → Actions** as `SERVER_SSH_KEY`. Also add:

- `SERVER_HOST`: your server’s Tailscale hostname (preferred) or Tailscale IP
- `SERVER_USER`: `tradebot`
- `TAILSCALE_OAUTH_CLIENT_ID` and `TAILSCALE_OAUTH_SECRET`: credentials for a tagged, ephemeral GitHub Actions Tailscale node

Create `.github/workflows/deploy.yml` in the repository with:

```yaml
name: Deploy Trade Bot

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: tailscale/github-action@v3
        with:
          oauth-client-id: ${{ secrets.TAILSCALE_OAUTH_CLIENT_ID }}
          oauth-secret: ${{ secrets.TAILSCALE_OAUTH_SECRET }}
          tags: tag:ci
      - uses: appleboy/ssh-action@v1.2.0
        with:
          host: ${{ secrets.SERVER_HOST }}
          username: ${{ secrets.SERVER_USER }}
          key: ${{ secrets.SERVER_SSH_KEY }}
          script: /opt/trade-bot/deploy.sh
```

Commit and push that workflow. Every later push to `main` pulls the new code, updates Python dependencies when needed, validates the backend syntax, restarts both services, and checks the local health endpoint.

## Everyday commands

```bash
# Check services
sudo systemctl status tradebot-api tradebot-worker --no-pager

# View live logs
sudo journalctl -u tradebot-api -u tradebot-worker -f

# Stop both services
sudo systemctl stop tradebot-api tradebot-worker

# Start both services
sudo systemctl start tradebot-api tradebot-worker

# Restart both services after a manual settings/code update
sudo systemctl restart tradebot-api tradebot-worker

# Confirm dashboard/API health
curl http://127.0.0.1:8000/health
```

## Secure remote access

Keep Uvicorn on `127.0.0.1`; do not expose port 8000 directly to the internet. Tailscale Serve provides the private HTTPS endpoint on port 443. Do not use Tailscale Funnel or a public unauthenticated webhook endpoint for deployment.
