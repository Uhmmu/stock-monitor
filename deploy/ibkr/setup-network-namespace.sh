#!/usr/bin/env bash
set -euo pipefail

namespace="stock-monitor-ibkr"
host_link="ibkr-host"
namespace_link="ibkr-ns"

if ! ip netns list | awk '{print $1}' | grep -qx "$namespace"; then
  ip netns add "$namespace"
fi
if ! ip link show "$host_link" >/dev/null 2>&1; then
  ip link add "$host_link" type veth peer name "$namespace_link"
  ip link set "$namespace_link" netns "$namespace"
fi
ip address replace 169.254.250.1/30 dev "$host_link"
ip link set "$host_link" up
ip netns exec "$namespace" ip address replace 169.254.250.2/30 dev "$namespace_link"
ip netns exec "$namespace" ip link set "$namespace_link" up
ip netns exec "$namespace" ip link set lo up
