#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"
baselines="$repo_root/apple/Tests/VisualBaselines/R5"

require_text() {
    pattern=$1
    target=$2
    message=$3
    if ! rg -q "$pattern" "$target"; then
        echo "R5 violation: $message"
        exit 1
    fi
}

forbid_text() {
    pattern=$1
    target=$2
    message=$3
    if rg -q "$pattern" "$target"; then
        echo "R5 violation: $message"
        exit 1
    fi
}

# R5.0: readable chat, recoverable stream activity, citations, and discovery funnel.
require_text 'struct AIStreamingResponseView' "$features/SemanticWorkspaceView.swift" 'Streaming answers need a stable assistant content column.'
require_text 'struct R5MarkdownContent' "$features/SemanticWorkspaceView.swift" 'Long answers need block-aware Markdown reading rhythm.'
require_text 'citationDisclosure' "$features/SemanticWorkspaceView.swift" 'Conversation citations must stay traceable.'
require_text 'struct DiscoveryFunnelView' "$features/ReadabilityR5.swift" 'Discovery must expose its validation and filtering funnel.'

# R5.1: portfolio hierarchy, multi-currency truth, jobs, journal editing, and IBKR grouping.
require_text 'struct PortfolioHoldingsTable' "$features/ReadabilityR5.swift" 'Portfolio positions need a native table with local/base currency columns.'
require_text 'valuation_available' "$features/ReadabilityR5.swift" 'Missing FX must remain an adjacent coverage gap.'
require_text 'struct JobStatusTimelineView' "$features/ReadabilityR5.swift" 'Analysis tasks need a status timeline.'
require_text 'struct JournalWorkspaceView' "$features/GoalM5Views.swift" 'Journal needs list/detail editing.'
require_text 'updateTradeLog' "$features/GoalM5Service.swift" 'Journal edits must round-trip through the service.'
require_text '现金、费用与 FX' "$features/ReadabilityR5.swift" 'IBKR needs a task-oriented account hierarchy.'

# R5.2: entity-driven Crypto/Quant, explicit PAPER, grouped settings/admin.
require_text 'struct R5EntityOption' "$features/ReadabilityR5.swift" 'Context detail pages need entity selectors.'
forbid_text 'func parameterBar' "$features/GoalM5Views.swift" 'Normal workflows must not ask users to type transport IDs.'
forbid_text '"instrument_id": "1"' "$features/GoalM5Views.swift" 'Placeholder ID defaults are not valid entity context.'
require_text 'struct QuantResearchFlowView' "$features/ReadabilityR5.swift" 'Quant needs a definitions-to-PAPER research flow.'
require_text 'struct PaperBoundaryView' "$features/ReadabilityR5.swift" 'Internal PAPER needs an explicit non-live boundary.'
require_text 'formStyle\(\.grouped\)' "$features/GoalM5Views.swift" 'Settings and journal editors must use native grouped forms.'
require_text 'struct AdministrationBoundaryView' "$features/ReadabilityR5.swift" 'Administration and execution controls must stay separated.'

baseline_count=$(find "$baselines" -type f -name 'r5-*.png' | wc -l | tr -d ' ')
if [ "$baseline_count" -ne 11 ]; then
    echo "R5 violation: expected 11 deterministic R5 baselines, found $baseline_count."
    exit 1
fi

"$repo_root/apple/scripts/verify-readability-r4.sh"

echo "Readability R5 gate passed. Complex AI, asset, broker, crypto, and administration workspaces are task-oriented."
