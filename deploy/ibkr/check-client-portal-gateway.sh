#!/usr/bin/env bash
set -euo pipefail

echo "Xray 状态"
systemctl is-active xray
echo "强制 SOCKS5h 入口"
ss -ltn | awk '$4 == "127.0.0.1:10808" { found=1; print } END { exit !found }'
echo "经 10808 代理的 HTTPS 出口（不打印凭据）"
curl --fail --silent --show-error --max-time 15 --proxy socks5h://127.0.0.1:10808 https://api.ipify.org >/dev/null
echo "Gateway 服务"
systemctl --no-pager --full status stock-monitor-ibkr-gateway.service
echo "Gateway 本机监听"
ss -ltn | awk '$4 == "127.0.0.1:5000" || $4 == "[::1]:5000" { found=1; print } END { exit !found }'
echo "检查通过。生产变更前还应人工确认代理出口属于预期的日本东京 AS2914 NTT。"
