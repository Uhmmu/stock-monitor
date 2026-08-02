#!/usr/bin/env bash
set -euo pipefail

IBKR_INSTALL_DIR="${IBKR_INSTALL_DIR:-/opt/stock-monitor/ibkr/clientportal.gw}"
IBKR_PROXY_HOST="${IBKR_PROXY_HOST:-127.0.0.1}"
IBKR_PROXY_PORT="${IBKR_PROXY_PORT:-10808}"

if ! timeout 2 bash -c "</dev/tcp/${IBKR_PROXY_HOST}/${IBKR_PROXY_PORT}" 2>/dev/null; then
  echo "拒绝启动：强制 IBKR SOCKS5h 代理 ${IBKR_PROXY_HOST}:${IBKR_PROXY_PORT} 不可用。不会 direct fallback。" >&2
  exit 1
fi
if [[ ! -x "$IBKR_INSTALL_DIR/bin/run.sh" || ! -f "$IBKR_INSTALL_DIR/root/conf.yaml" ]]; then
  echo "Client Portal Gateway 安装不完整：$IBKR_INSTALL_DIR" >&2
  exit 1
fi
IBKR_PROXYCHAINS_CONFIG="${IBKR_PROXYCHAINS_CONFIG:-$(dirname "$IBKR_INSTALL_DIR")/proxychains.conf}"
if ! command -v proxychains4 >/dev/null 2>&1 || [[ ! -r "$IBKR_PROXYCHAINS_CONFIG" ]]; then
  echo "拒绝启动：缺少 proxychains4 或专用配置，无法保证 SOCKS5h 远端 DNS。" >&2
  exit 1
fi
if grep -Eq '^[[:space:]]*listenPort:[[:space:]]*5000' "$IBKR_INSTALL_DIR/root/conf.yaml"; then :; else
  echo "警告：conf.yaml 未显式使用默认 5000 端口，请人工核对 loopback 监听和 SSH 隧道。" >&2
fi

# The Gateway is Java. These JVM SOCKS properties force its IBKR upstream traffic
# through the local Xray/VLESS SOCKS5 endpoint. A dead proxy makes connections fail.
export JAVA_TOOL_OPTIONS="${JAVA_TOOL_OPTIONS:-} -DsocksProxyHost=${IBKR_PROXY_HOST} -DsocksProxyPort=${IBKR_PROXY_PORT} -Djava.net.useSystemProxies=false"
cd "$IBKR_INSTALL_DIR"
exec proxychains4 -f "$IBKR_PROXYCHAINS_CONFIG" ./bin/run.sh root/conf.yaml
