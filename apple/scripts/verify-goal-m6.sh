#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
apple_root="$repo_root/apple"

test "$(uname -m)" = arm64
plutil -lint "$apple_root/Apps/StockMonitorMac/PrivacyInfo.xcprivacy"
python3 "$apple_root/scripts/verify-parity-matrix.py"
swiftformat --lint --config "$apple_root/.swiftformat" "$apple_root/Apps" "$apple_root/Packages" "$apple_root/Tests"
swiftlint lint --config "$apple_root/.swiftlint.yml" --working-directory "$apple_root"
swift test --package-path "$apple_root/Packages/StockMonitorCore"
swift test --package-path "$apple_root/Packages/StockMonitorDesign"
swift test --package-path "$apple_root/Packages/StockMonitorFeatures"
PYTHONPATH="$repo_root/backend" "$repo_root/.venv/bin/python" -m pytest -q \
    "$repo_root/backend/tests/test_auth_sessions.py" \
    "$repo_root/backend/tests/test_macos_auth_contract.py" \
    "$repo_root/backend/tests/test_macos_client_capabilities.py"
swift build --package-path "$apple_root" -c release --arch arm64
"$apple_root/scripts/build-local-app.sh"
"$apple_root/scripts/verify-app-security.sh"
xcodegen generate --spec "$apple_root/project.yml" --project "$apple_root"
xcodebuild \
    -workspace "$apple_root/StockMonitor.xcworkspace" \
    -scheme StockMonitorMac \
    -configuration Release \
    -destination 'platform=macOS,arch=arm64' \
    CODE_SIGNING_ALLOWED=NO \
    build
xcodebuild \
    -workspace "$apple_root/StockMonitor.xcworkspace" \
    -scheme StockMonitorMac \
    -configuration Debug \
    -destination 'platform=macOS,arch=arm64' \
    CODE_SIGN_IDENTITY=- \
    test
"$apple_root/scripts/build-release-candidate.sh"
"$apple_root/scripts/rehearse-local-rollback.sh"
"$apple_root/scripts/distribution-status.sh"
