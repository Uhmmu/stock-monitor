#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
team_id=${STOCK_MONITOR_DEVELOPMENT_TEAM:-}
notary_profile=${STOCK_MONITOR_NOTARY_PROFILE:-}

if [ -z "$team_id" ] || [ -z "$notary_profile" ]; then
    echo "Set STOCK_MONITOR_DEVELOPMENT_TEAM and STOCK_MONITOR_NOTARY_PROFILE locally" >&2
    exit 1
fi

"$apple_root/scripts/archive.sh"

archive_root="$apple_root/DerivedData/archives"
archive_path="$archive_root/StockMonitor.xcarchive"
export_root="$archive_root/export"
export_options="$archive_root/ExportOptions.plist"
zip_path="$archive_root/StockMonitor.zip"
app_path="$export_root/Stock Monitor.app"

rm -rf "$export_root"
rm -f "$export_options" "$zip_path"
plutil -create xml1 "$export_options"
plutil -insert method -string developer-id "$export_options"
plutil -insert signingStyle -string automatic "$export_options"
plutil -insert teamID -string "$team_id" "$export_options"

xcodebuild -exportArchive \
    -archivePath "$archive_path" \
    -exportPath "$export_root" \
    -exportOptionsPlist "$export_options"

codesign --verify --deep --strict --verbose=2 "$app_path"
ditto -c -k --keepParent "$app_path" "$zip_path"
xcrun notarytool submit "$zip_path" --keychain-profile "$notary_profile" --wait
xcrun stapler staple "$app_path"
xcrun stapler validate "$app_path"
spctl --assess --type execute --verbose=2 "$app_path"

printf '%s\n' "$app_path"
