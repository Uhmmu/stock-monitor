#!/usr/bin/env bash
set -euo pipefail

if ! ip netns list | awk '{print $1}' | grep -qx stock-monitor-ibkr; then
  echo "IBKR network namespace 尚未创建" >&2
  exit 1
fi
if ! timeout 2 bash -c '</dev/tcp/127.0.0.1/10808' 2>/dev/null; then
  echo "拒绝启动：宿主机 127.0.0.1:10808 不可用" >&2
  exit 1
fi

cleanup() {
  kill "${gateway_relay_pid:-}" "${proxy_relay_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
socat TCP4-LISTEN:5000,bind=127.0.0.1,reuseaddr,fork TCP4:169.254.250.2:5000 &
gateway_relay_pid=$!
socat TCP4-LISTEN:10808,bind=169.254.250.1,reuseaddr,fork TCP4:127.0.0.1:10808 &
proxy_relay_pid=$!
wait -n "$gateway_relay_pid" "$proxy_relay_pid"
echo "IBKR namespace relay 意外退出" >&2
exit 1
