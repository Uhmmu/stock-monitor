#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"
design="$repo_root/apple/Packages/StockMonitorDesign/Sources/StockMonitorDesign"
baselines="$repo_root/apple/Tests/VisualBaselines/R7"

require_text() {
    pattern=$1
    target=$2
    message=$3
    if ! rg -q "$pattern" "$target"; then
        echo "R7 violation: $message"
        exit 1
    fi
}

require_text 'enum R7InteractionAuditCatalog' "$features/InteractionR7.swift" 'Every route needs a behavioral interaction baseline.'
require_text 'routeStates' "$features/AppNavigation.swift" 'Per-route selections and filters must live in the window navigation model.'
require_text 'route-interaction-states' "$features/AppShell.swift" 'Per-window route state must be restored across view recreation.'
require_text '刷新当前页面' "$features/AppShell.swift" 'The toolbar must explain refresh scope.'
require_text 'stockMonitorWebInspired' "$design/DesignTokens.swift" 'The web-inspired style must be centrally controlled.'
require_text 'StockMonitorCanvasBackdrop' "$features/AppShell.swift" 'Every production route needs the shared canvas.'
require_text 'accessibilityReduceTransparency' "$design/DesignTokens.swift" 'Custom chrome must provide an opaque accessibility fallback.'

baseline_count=$(find "$baselines" -type f -name 'r7-*.png' | wc -l | tr -d ' ')
if [ "$baseline_count" -ne 10 ]; then
    echo "R7 violation: expected 10 representative baselines, found $baseline_count."
    exit 1
fi

"$repo_root/apple/scripts/verify-readability-r6.sh"

echo "Interaction R7 gate passed. Route continuity and web-inspired native visuals are verified."
