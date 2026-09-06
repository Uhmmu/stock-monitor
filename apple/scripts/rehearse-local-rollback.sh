#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
candidate="$apple_root/DerivedData/release-candidate/staging/Stock Monitor.app"
rehearsal_root=$(mktemp -d "$apple_root/DerivedData/rollback-rehearsal.XXXXXX")
installed="$rehearsal_root/Applications/Stock Monitor.app"
backup="$rehearsal_root/Backup/Stock Monitor.app"
support_data="$rehearsal_root/Application Support/user-state-sentinel"

cleanup() {
    case "$rehearsal_root" in
        "$apple_root"/DerivedData/rollback-rehearsal.*) rm -rf "$rehearsal_root" ;;
        *) echo "Refusing unsafe cleanup path" >&2; exit 1 ;;
    esac
}
trap cleanup EXIT HUP INT TERM

test -d "$candidate"
mkdir -p "$(dirname "$installed")" "$(dirname "$backup")" "$(dirname "$support_data")"
ditto "$candidate" "$installed"
printf 'server-owned-data-must-remain-untouched\n' > "$support_data"
before_checksum=$(shasum -a 256 "$installed/Contents/MacOS/StockMonitorMac" | awk '{print $1}')
ditto "$installed" "$backup"

rm -rf "$installed"
ditto "$candidate" "$installed"
codesign --verify --deep --strict --verbose=2 "$installed"
test "$(lipo -archs "$installed/Contents/MacOS/StockMonitorMac")" = arm64

rm -rf "$installed"
ditto "$backup" "$installed"
after_checksum=$(shasum -a 256 "$installed/Contents/MacOS/StockMonitorMac" | awk '{print $1}')
test "$before_checksum" = "$after_checksum"
test "$(sed -n '1p' "$support_data")" = server-owned-data-must-remain-untouched

printf 'rollback_rehearsal=passed\napplication_state=preserved\n'
