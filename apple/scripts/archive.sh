#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
team_id=${STOCK_MONITOR_DEVELOPMENT_TEAM:-}

if [ -z "$team_id" ]; then
    echo "Set STOCK_MONITOR_DEVELOPMENT_TEAM locally; never commit the Team identifier" >&2
    exit 1
fi

"$apple_root/scripts/doctor.sh"
archive_root="$apple_root/DerivedData/archives"
mkdir -p "$archive_root"
xcodebuild \
    -workspace "$apple_root/StockMonitor.xcworkspace" \
    -scheme StockMonitorMac \
    -configuration Release \
    -destination 'generic/platform=macOS' \
    -archivePath "$archive_root/StockMonitor.xcarchive" \
    DEVELOPMENT_TEAM="$team_id" \
    CODE_SIGN_STYLE=Automatic \
    -allowProvisioningUpdates \
    archive

codesign --verify --deep --strict --verbose=2 \
    "$archive_root/StockMonitor.xcarchive/Products/Applications/Stock Monitor.app"
