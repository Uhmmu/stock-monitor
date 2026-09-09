#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"
design="$repo_root/apple/Packages/StockMonitorDesign/Sources/StockMonitorDesign"
baselines="$repo_root/apple/Tests/VisualBaselines/R3"

require_text() {
    pattern=$1
    target=$2
    message=$3
    if ! rg -q "$pattern" "$target"; then
        echo "R3 violation: $message"
        exit 1
    fi
}

require_text 'case function, security, conversation, report' "$features/AppNavigation.swift" 'Command-K must group functions, stocks, conversations, and reports.'
require_text 'case company, portfolio, ai, crypto' "$features/AppNavigation.swift" 'Company, Portfolio, AI, and Crypto secondary workspaces are required.'
require_text 'navigation-favorites' "$features/AppShell.swift" 'Sidebar favorites must be restorable.'
require_text 'navigation-route-order' "$features/AppShell.swift" 'User route ordering must be restorable.'
require_text 'resetNavigationLayout' "$features/AppShell.swift" 'The shell must expose a restore-default-layout action.'
require_text 'case narrow, standard, wide' "$design/DesignTokens.swift" 'Explicit narrow, standard, and wide breakpoints are required.'
require_text 'ViewThatFits' "$design/SemanticComponents.swift" 'Shared page anatomy must adapt explicitly instead of compressing passively.'

baseline_count=$(find "$baselines" -type f -name 'r3-*.png' | wc -l | tr -d ' ')
if [ "$baseline_count" -ne 5 ]; then
    echo "R3 violation: expected 5 deterministic navigation/anatomy baselines, found $baseline_count."
    exit 1
fi

"$repo_root/apple/scripts/verify-readability-r2.sh"
echo "Readability R3 gate passed. Navigation, page anatomy, adaptive widths, and layout restoration are present."
