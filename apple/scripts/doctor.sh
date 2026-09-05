#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
developer_dir=$(xcode-select -p)

case "$developer_dir" in
    */Xcode.app/Contents/Developer) ;;
    *) echo "Full stable Xcode is not selected: $developer_dir" >&2; exit 1 ;;
esac

xcodebuild -version
xcrun --sdk macosx --show-sdk-version
xcrun --sdk macosx --show-sdk-platform-version
swift --version
test "$(uname -m)" = arm64

xcodegen generate --spec "$apple_root/project.yml" --project "$apple_root"
xcodebuild \
    -workspace "$apple_root/StockMonitor.xcworkspace" \
    -scheme StockMonitorMac \
    -configuration Release \
    -destination 'platform=macOS,arch=arm64' \
    CODE_SIGNING_ALLOWED=NO \
    build

if ! security find-certificate -a -c 'Apple Development' >/dev/null 2>&1 \
    && ! security find-certificate -a -c 'Developer ID Application' >/dev/null 2>&1; then
    echo "No Apple Development or Developer ID Application certificate found" >&2
    exit 1
fi
