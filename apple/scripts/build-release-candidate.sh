#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
candidate_root="$apple_root/DerivedData/release-candidate"
staging_root="$candidate_root/staging"
app_source="$apple_root/DerivedData/local-app/Stock Monitor.app"
dmg_path="$candidate_root/Stock-Monitor-0.1.0-arm64-local.dmg"
checksum_path="$dmg_path.sha256"

case "$candidate_root" in
    "$apple_root"/DerivedData/*) ;;
    *) echo "Refusing unsafe output path" >&2; exit 1 ;;
esac

"$apple_root/scripts/build-local-app.sh"
rm -rf "$candidate_root"
mkdir -p "$staging_root"
ditto "$app_source" "$staging_root/Stock Monitor.app"
cp "$apple_root/RELEASE_NOTES.md" "$staging_root/Release Notes.md"
cp "$apple_root/LOCAL_BUILD_NOTICE.md" "$staging_root/LOCAL BUILD - READ FIRST.md"
hdiutil create -quiet -fs HFS+ -format UDZO -volname "Stock Monitor Local" -srcfolder "$staging_root" "$dmg_path"
shasum -a 256 "$dmg_path" > "$checksum_path"

test "$(lipo -archs "$staging_root/Stock Monitor.app/Contents/MacOS/StockMonitorMac")" = arm64
codesign --verify --deep --strict --verbose=2 "$staging_root/Stock Monitor.app"
printf '%s\n%s\n' "$dmg_path" "$checksum_path"
