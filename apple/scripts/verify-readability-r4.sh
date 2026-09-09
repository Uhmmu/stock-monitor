#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"
baselines="$repo_root/apple/Tests/VisualBaselines/R4"

require_text() {
    pattern=$1
    target=$2
    message=$3
    if ! rg -q "$pattern" "$target"; then
        echo "R4 violation: $message"
        exit 1
    fi
}

forbid_text() {
    pattern=$1
    target=$2
    message=$3
    if rg -q "$pattern" "$target"; then
        echo "R4 violation: $message"
        exit 1
    fi
}

# R4.0：总览首屏四状态与对齐指数条
require_text 'struct OverviewCoreStateStrip' "$features/ReadabilityR4.swift" 'Overview must expose market/portfolio/watchlist/alerts in the first screen.'
require_text 'struct IndexMetricStrip' "$features/ReadabilityR4.swift" 'Index quotes must render in an aligned metric strip.'
require_text 'struct AlertSummaryRow' "$features/ReadabilityR4.swift" 'Alert rows must state what happened plus investigation status.'
require_text 'AlertGrouper.buckets' "$features/GoalM3Views.swift" 'Alerts center must group by severity/time/investigation status.'

# R4.0：自选股表格与 inspector 编辑
require_text 'alternatingRowBackgrounds\(\.enabled\)' "$features/GoalM3Views.swift" 'Watchlist table must use alternating row backgrounds.'
require_text 'enum WatchlistSortKey' "$features/GoalM3Views.swift" 'Watchlist table must expose an explicit sort control.'
require_text 'struct WatchlistThresholdDraft' "$features/GoalM3Views.swift" 'Threshold editing must live in the inspector, not a sheet jump.'
forbid_text 'struct ThresholdEditor' "$features/GoalM3Views.swift" 'ThresholdEditor sheet was removed by R4.0; keep thresholds inline.'

# R4.1：阅读体验
require_text 'struct NewsListRow' "$features/GoalM3ReadingViews.swift" 'News list rows must lead with the title and demote AI status.'
require_text 'struct CalendarAgendaRow' "$features/ReadabilityR4.swift" 'Calendar must render an agenda with symbol+text type semantics.'
require_text 'struct ReportReaderView' "$features/GoalM3ReadingViews.swift" 'Report reading must offer outline, copy, and back-to-security.'

# R4.2：统一公司头与语义重排
require_text 'struct CompanyHeaderView' "$features/ReadabilityR4.swift" 'Company pages must share one CompanyHeader.'
require_text 'companySummary.loadIfNeeded' "$features/GoalM4Views.swift" 'Company workspace must hydrate the shared quote context.'
require_text 'FinancialMatrixTable' "$features/GoalM4Views.swift" 'Financials must use the period-aligned matrix with frozen metric column.'
require_text 'firstScreenSummary' "$features/GoalM4Views.swift" 'Valuation first screen must show applicability/consensus/upside/conflict.'
require_text 'SecEventTimelineRow' "$features/GoalM4CompanyViews.swift" 'SEC events must render as a timeline with evidence links.'
require_text 'sideMetrics' "$features/TechnicalAnalysisView.swift" 'Technical analysis must pair the chart with a side metric column.'

# R4 快照基线：Before/After 均需存在
baseline_count=$(find "$baselines" -type f -name 'r4-*.png' | wc -l | tr -d ' ')
if [ "$baseline_count" -ne 11 ]; then
    echo "R4 violation: expected 11 deterministic R4 baselines, found $baseline_count."
    exit 1
fi

"$repo_root/apple/scripts/verify-readability-r3.sh"

echo "Readability R4 gate passed. High-frequency market and research pages are semantic, aligned, and visually baselined."
