#!/usr/bin/env bash
set -euo pipefail

IBKR_GATEWAY_DOWNLOAD_URL="${IBKR_GATEWAY_DOWNLOAD_URL:-https://download2.interactivebrokers.com/portal/clientportal.gw.zip}"
IBKR_INSTALL_DIR="${IBKR_INSTALL_DIR:-/opt/stock-monitor/ibkr/clientportal.gw}"
IBKR_SERVICE_USER="${IBKR_SERVICE_USER:-stock-monitor}"

if [[ ! -r /etc/os-release ]]; then
  echo "无法识别操作系统；本脚本仅支持 Debian/Ubuntu。" >&2
  exit 1
fi
. /etc/os-release
if [[ "${ID:-}" != "debian" && "${ID:-}" != "ubuntu" && "${ID_LIKE:-}" != *debian* ]]; then
  echo "当前系统 ${ID:-unknown} 未经支持；请手工安装 Java 17、unzip、curl 和 ca-certificates。" >&2
  exit 1
fi

missing=()
if ! command -v java >/dev/null 2>&1; then
  if apt-cache show openjdk-17-jre-headless 2>/dev/null | grep -q '^Package:'; then
    missing+=(openjdk-17-jre-headless)
  elif apt-cache show openjdk-21-jre-headless 2>/dev/null | grep -q '^Package:'; then
    missing+=(openjdk-21-jre-headless)
  else
    echo "未找到受支持的 OpenJDK headless JRE（17 或 21）。" >&2
    exit 1
  fi
fi
command -v unzip >/dev/null 2>&1 || missing+=(unzip)
command -v curl >/dev/null 2>&1 || missing+=(curl)
command -v proxychains4 >/dev/null 2>&1 || missing+=(proxychains4)
dpkg -s ca-certificates >/dev/null 2>&1 || missing+=(ca-certificates)
if ((${#missing[@]})); then
  echo "正在安装缺少的依赖：${missing[*]}"
  sudo apt-get update
  sudo apt-get install -y "${missing[@]}"
fi

if ! id "$IBKR_SERVICE_USER" >/dev/null 2>&1; then
  echo "服务用户 $IBKR_SERVICE_USER 不存在。请先创建非 root 系统用户，例如：" >&2
  echo "sudo useradd --system --home /opt/stock-monitor/ibkr --shell /usr/sbin/nologin $IBKR_SERVICE_USER" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
archive="$tmp_dir/clientportal.gw.zip"
if ! timeout 2 bash -c '</dev/tcp/127.0.0.1/10808' 2>/dev/null; then
  echo "拒绝下载：强制 IBKR SOCKS5h 代理 127.0.0.1:10808 不可用。不会 direct fallback。" >&2
  exit 1
fi
curl --fail --location --proto '=https' --tlsv1.2 \
  --proxy socks5h://127.0.0.1:10808 --output "$archive" "$IBKR_GATEWAY_DOWNLOAD_URL"
if ! unzip -t "$archive" >/dev/null; then
  echo "下载内容不是有效 ZIP；可能收到了 HTML 错误页。安装已中止。" >&2
  exit 1
fi

staged="$tmp_dir/unpacked"
mkdir -p "$staged"
unzip -q "$archive" -d "$staged"
source_dir="$(find "$staged" -type f -path '*/bin/run.sh' -printf '%h\n' | sed 's#/bin$##' | head -n 1)"
if [[ -z "$source_dir" || ! -f "$source_dir/root/conf.yaml" ]]; then
  echo "ZIP 结构不符合 Client Portal Gateway 预期，未找到 bin/run.sh 或 root/conf.yaml。" >&2
  exit 1
fi

sudo install -d -o "$IBKR_SERVICE_USER" -g "$IBKR_SERVICE_USER" "$(dirname "$IBKR_INSTALL_DIR")"
if [[ -e "$IBKR_INSTALL_DIR" ]]; then
  backup="${IBKR_INSTALL_DIR}.backup-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "检测到已有安装，将完整备份到 $backup；不会原地覆盖自定义配置。"
  sudo mv "$IBKR_INSTALL_DIR" "$backup"
fi
sudo mv "$source_dir" "$IBKR_INSTALL_DIR"
sudo chown -R "$IBKR_SERVICE_USER:$IBKR_SERVICE_USER" "$IBKR_INSTALL_DIR"
sudo chmod -R u=rwX,g=rX,o= "$IBKR_INSTALL_DIR"
gateway_conf="$IBKR_INSTALL_DIR/root/conf.yaml"
if ! grep -q '169\.254\.250\.1' "$gateway_conf"; then
  sudo cp -a "$gateway_conf" "$gateway_conf.pre-stock-monitor-netns"
  sudo sed -i '/- 127\.0\.0\.1/a\        - 169.254.250.1' "$gateway_conf"
fi
sudo chown "$IBKR_SERVICE_USER:$IBKR_SERVICE_USER" "$gateway_conf"
sudo chmod 0640 "$gateway_conf"
sudo install -m 0755 -o root -g root "$(dirname "$0")/start-client-portal-gateway.sh" "$(dirname "$IBKR_INSTALL_DIR")/start-client-portal-gateway.sh"
sudo install -m 0644 -o root -g root "$(dirname "$0")/proxychains.conf" "$(dirname "$IBKR_INSTALL_DIR")/proxychains.conf"
sudo install -m 0644 -o root -g root "$(dirname "$0")/proxychains-netns.conf" "$(dirname "$IBKR_INSTALL_DIR")/proxychains-netns.conf"
sudo install -m 0755 -o root -g root "$(dirname "$0")/start-docker-relays.sh" "$(dirname "$IBKR_INSTALL_DIR")/start-docker-relays.sh"
sudo install -m 0755 -o root -g root "$(dirname "$0")/setup-network-namespace.sh" "$(dirname "$IBKR_INSTALL_DIR")/setup-network-namespace.sh"
sudo install -m 0755 -o root -g root "$(dirname "$0")/start-network-namespace-relays.sh" "$(dirname "$IBKR_INSTALL_DIR")/start-network-namespace-relays.sh"

echo "安装完成：$IBKR_INSTALL_DIR"
echo "安装脚本没有开放防火墙，也没有把 Gateway 绑定到 0.0.0.0。"
echo "启动前请确认 Xray SOCKS5h 入口仅监听 127.0.0.1:10808，再安装 systemd 示例。"
echo "登录时在个人电脑运行：ssh -L 5000:127.0.0.1:5000 <user>@<vps-host>"
