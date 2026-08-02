# IBKR Client Portal Gateway on a headless VPS

This directory installs the official Java Gateway without a desktop, X11, or virtual display. The API image uses headless Chromium to submit the official SRP login flow; IB Key approval remains on the user's phone. Port 5000 and the Xray SOCKS port 10808 must remain private and must not bind to a public interface.

## Install and start

```bash
sudo useradd --system --home /opt/stock-monitor/ibkr --shell /usr/sbin/nologin stock-monitor
sudo ./deploy/ibkr/install-client-portal-gateway.sh
sudo install -m 0644 deploy/ibkr/stock-monitor-ibkr-network.service /etc/systemd/system/
sudo install -m 0644 deploy/ibkr/stock-monitor-ibkr-namespace-relays.service /etc/systemd/system/
sudo install -m 0644 deploy/ibkr/stock-monitor-ibkr-gateway.service /etc/systemd/system/
sudo install -m 0644 deploy/ibkr/stock-monitor-ibkr-docker-relays.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now stock-monitor-ibkr-network
sudo systemctl enable --now stock-monitor-ibkr-namespace-relays
sudo systemctl enable --now stock-monitor-ibkr-gateway
sudo systemctl enable --now stock-monitor-ibkr-docker-relays
sudo systemctl status stock-monitor-ibkr-gateway
journalctl -u stock-monitor-ibkr-gateway -f
```

Before starting, verify Xray is active and `127.0.0.1:10808` works as a `socks5h` proxy. Because the official Gateway binds a wildcard socket, production runs it inside a dedicated Linux network namespace. Only a host `127.0.0.1:5000` relay reaches it; its only outbound path is the namespace veth SOCKS relay to host `127.0.0.1:10808`. A dedicated `proxychains4` `strict_chain + proxy_dns` configuration (the equivalent of `socks5h` remote resolution), plus JVM SOCKS properties, makes proxy failure fail closed. There is no direct fallback.

## Log in from your computer

```bash
ssh -L 5000:127.0.0.1:5000 <user>@<vps-host>
```

Open `https://localhost:5000`. Accept the expected self-signed certificate warning, enter the IBKR username and password only on that official Gateway page, and approve IB Key in the IBKR mobile app. Return to stock-monitor and manually check authentication. stock-monitor never receives the password.

## Stop or uninstall

```bash
sudo systemctl disable --now stock-monitor-ibkr-gateway
sudo rm /etc/systemd/system/stock-monitor-ibkr-gateway.service
sudo systemctl daemon-reload
```

Disable the four `stock-monitor-ibkr-*` units first. After making a backup if desired, remove only the explicit Gateway directory and IBKR namespace/relay files under `/opt/stock-monitor/ibkr`. Do not remove the shared Xray service or proxy configuration.
