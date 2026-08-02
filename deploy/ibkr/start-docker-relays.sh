#!/usr/bin/env bash
set -euo pipefail

IBKR_DOCKER_NETWORK="${IBKR_DOCKER_NETWORK:-stock-monitor_default}"
bridge_ip="$(docker network inspect "$IBKR_DOCKER_NETWORK" --format '{{(index .IPAM.Config 0).Gateway}}')"
case "$bridge_ip" in
  10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) ;;
  *) echo "拒绝启动：Docker bridge 地址 $bridge_ip 不在允许的私有地址范围" >&2; exit 1 ;;
esac
if ! timeout 2 bash -c '</dev/tcp/127.0.0.1/10808' 2>/dev/null; then
  echo "拒绝启动：127.0.0.1:10808 不可用" >&2
  exit 1
fi

cleanup() {
  kill "${gateway_relay_pid:-}" "${proxy_relay_pid:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
socat "TCP4-LISTEN:5000,bind=$bridge_ip,reuseaddr,fork" TCP4:127.0.0.1:5000 &
gateway_relay_pid=$!
socat "TCP4-LISTEN:10808,bind=$bridge_ip,reuseaddr,fork" TCP4:127.0.0.1:10808 &
proxy_relay_pid=$!
wait -n "$gateway_relay_pid" "$proxy_relay_pid"
echo "IBKR Docker relay 意外退出" >&2
exit 1
