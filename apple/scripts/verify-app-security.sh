#!/bin/sh
set -eu

apple_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
app_path=${1:-"$apple_root/DerivedData/local-app/Stock Monitor.app"}
executable="$app_path/Contents/MacOS/StockMonitorMac"
temporary_root=$(mktemp -d "$apple_root/DerivedData/security-audit.XXXXXX")
entitlements_path="$temporary_root/entitlements.plist"
libraries_path="$temporary_root/libraries.txt"

cleanup() {
    case "$temporary_root" in
        "$apple_root"/DerivedData/security-audit.*) rm -rf "$temporary_root" ;;
        *) echo "Refusing unsafe cleanup path" >&2; exit 1 ;;
    esac
}
trap cleanup EXIT HUP INT TERM

test -d "$app_path"
test "$(lipo -archs "$executable")" = arm64
codesign --verify --deep --strict --verbose=2 "$app_path"
codesign -dvv "$app_path" 2>&1 | grep -q 'flags=.*runtime'

codesign -d --entitlements :- "$app_path" 2>&1 | sed -n '/^<?xml/,$p' > "$entitlements_path"
test "$(/usr/libexec/PlistBuddy -c 'Print :com.apple.security.app-sandbox' "$entitlements_path")" = true
test "$(/usr/libexec/PlistBuddy -c 'Print :com.apple.security.network.client' "$entitlements_path")" = true
if /usr/libexec/PlistBuddy -c 'Print :com.apple.security.get-task-allow' "$entitlements_path" >/dev/null 2>&1; then
    echo "Release candidate must not include get-task-allow" >&2
    exit 1
fi
if /usr/libexec/PlistBuddy -c 'Print :com.apple.security.network.server' "$entitlements_path" >/dev/null 2>&1; then
    echo "Release candidate must not accept inbound network connections" >&2
    exit 1
fi

plutil -lint "$app_path/Contents/Resources/PrivacyInfo.xcprivacy"
test "$(plutil -extract NSPrivacyTracking raw "$app_path/Contents/Resources/PrivacyInfo.xcprivacy")" = false
if plutil -extract NSAppTransportSecurity.NSAllowsArbitraryLoads raw "$app_path/Contents/Info.plist" >/dev/null 2>&1; then
    echo "NSAllowsArbitraryLoads must not be present" >&2
    exit 1
fi

otool -L "$executable" > "$libraries_path"
if grep -E '/opt/homebrew|/usr/local|@rpath|@loader_path' "$libraries_path" >/dev/null; then
    echo "Candidate links an unexpected non-system runtime" >&2
    exit 1
fi
if find "$app_path/Contents/Frameworks" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
    echo "Candidate unexpectedly embeds a third-party framework" >&2
    exit 1
fi
if rg -n 'import WebKit|WKWebView' "$apple_root/Apps" "$apple_root/Packages" >/dev/null; then
    echo "WebView is not permitted as an application surface" >&2
    exit 1
fi
if rg -n 'URLSession[.(]' "$apple_root/Packages/StockMonitorFeatures" "$apple_root/Packages/StockMonitorDesign" >/dev/null; then
    echo "Feature and design packages must not own URLSession" >&2
    exit 1
fi

printf 'security_audit=passed\narchitecture=arm64\nhardened_runtime=true\napp_sandbox=true\n'
