#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
output_root="$apple_root/DerivedData/local-app"
app_bundle="$output_root/Stock Monitor.app"
contents="$app_bundle/Contents"
executable="$apple_root/.build/arm64-apple-macosx/release/StockMonitorMac"
icon_source="$apple_root/Apps/StockMonitorMac/Assets.xcassets/AppIcon.appiconset"
icon_work="$output_root/AppIcon.iconset"

case "$output_root" in
    "$apple_root"/DerivedData/*) ;;
    *) echo "Refusing unsafe output path" >&2; exit 1 ;;
esac

swift build --package-path "$apple_root" -c release --arch arm64
rm -rf "$output_root"
mkdir -p "$contents/MacOS" "$contents/Resources"
cp "$executable" "$contents/MacOS/StockMonitorMac"
mkdir -p "$icon_work"
cp "$icon_source"/icon_*.png "$icon_work/"
iconutil -c icns "$icon_work" -o "$contents/Resources/AppIcon.icns"
rm -rf "$icon_work"

plutil -create xml1 "$contents/Info.plist"
plutil -insert CFBundleDevelopmentRegion -string zh_CN "$contents/Info.plist"
plutil -insert CFBundleDisplayName -string "Stock Monitor" "$contents/Info.plist"
plutil -insert CFBundleExecutable -string StockMonitorMac "$contents/Info.plist"
plutil -insert CFBundleIconFile -string AppIcon "$contents/Info.plist"
plutil -insert CFBundleIdentifier -string com.jiale.StockMonitor "$contents/Info.plist"
plutil -insert CFBundleInfoDictionaryVersion -string 6.0 "$contents/Info.plist"
plutil -insert CFBundleName -string "Stock Monitor" "$contents/Info.plist"
plutil -insert CFBundlePackageType -string APPL "$contents/Info.plist"
plutil -insert CFBundleShortVersionString -string 0.1.0 "$contents/Info.plist"
plutil -insert CFBundleVersion -string 1 "$contents/Info.plist"
plutil -insert LSApplicationCategoryType -string public.app-category.finance "$contents/Info.plist"
plutil -insert LSMinimumSystemVersion -string 26.0 "$contents/Info.plist"
plutil -insert NSAppTransportSecurity -json '{"NSAllowsLocalNetworking":true}' "$contents/Info.plist"
plutil -insert StockMonitorAPIBaseURL -string http://127.0.0.1:8000 "$contents/Info.plist"
plutil -insert StockMonitorAPIEnvironment -string debug "$contents/Info.plist"

codesign --force --sign - --options runtime \
    --entitlements "$apple_root/Apps/StockMonitorMac/StockMonitorMac.entitlements" \
    "$app_bundle"
codesign --verify --deep --strict --verbose=2 "$app_bundle"
printf '%s\n' "$app_bundle"
