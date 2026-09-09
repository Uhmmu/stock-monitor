#!/bin/sh
set -eu

repo_root=$(git rev-parse --show-toplevel)
features="$repo_root/apple/Packages/StockMonitorFeatures/Sources/StockMonitorFeatures"
design="$repo_root/apple/Packages/StockMonitorDesign/Sources/StockMonitorDesign"
baselines="$repo_root/apple/Tests/VisualBaselines/R6"

require_text() {
    pattern=$1
    target=$2
    message=$3
    if ! rg -q "$pattern" "$target"; then
        echo "R6 violation: $message"
        exit 1
    fi
}

# R6.0: table audit, sortable columns, unified chart chrome, palette non-color encoding.
require_text 'enum R6TableAuditCatalog' "$features/ReadabilityR6.swift" 'All native tables must be registered in the column audit catalog.'
require_text 'sortOrder: \$' "$features/GoalM4OwnershipViews.swift" 'Ownership tables need native sortable columns.'
require_text 'sortOrder: \$' "$features/GoalM4CompanyViews.swift" 'SEC/congress tables need native sortable columns.'
require_text 'sortOrder: \$' "$features/OptionsViews.swift" 'Options chain needs native sortable columns.'
require_text 'sortOrder: \$' "$features/IndustryPulseViews.swift" 'Industry overview needs native sortable columns.'
require_text 'NumericTableCell' "$design/TableFoundation.swift" 'Numeric cells need trailing tabular figures with missing semantics.'
require_text 'struct ChartPanel' "$design/ChartChrome.swift" 'Charts need unified title/unit/source/as-of/unavailable chrome.'
require_text 'ChartSeriesSummaryTable' "$design/ChartChrome.swift" 'Charts need an equivalent text data summary.'
require_text 'struct YieldCurveChart' "$features/TechnicalChartKit.swift" 'The macro yield curve needs the shared chart treatment.'
require_text 'seriesMarker' "$design/ChartChrome.swift" 'Chart series need non-color encoding via shape markers.'
require_text 'LineSeriesSummaryBuilder' "$features/TechnicalChartKit.swift" 'Line charts must build text summaries for non-visual access.'
require_text 'TableTruncationFooter' "$design/TableFoundation.swift" 'Row caps need a recoverable truncation footer.'

# R6.1: material layering + restrained motion.
require_text 'MaterialPolicyCatalog' "$design/MotionAndMaterial.swift" 'Material usage must be audited per layer.'
require_text 'subtleHoverHighlight' "$design/MotionAndMaterial.swift" 'Custom clickable surfaces need subtle hover feedback.'
require_text 'StockMonitorMotionAudit' "$design/MotionAndMaterial.swift" 'High-frequency paths must be audited as animation-free.'

# R6.2: accessibility catalog, issue ledger with zero open P0/P1, five-layer parity.
require_text 'enum R6AccessibilityCatalog' "$features/ReadabilityR6.swift" 'Every route needs reading-order anchors and a keyboard path.'
require_text 'enum R6IssueLedger' "$features/ReadabilityR6.swift" 'P0–P3 findings need a closure ledger.'
require_text 'enum R6AcceptanceCatalog' "$features/ReadabilityR6.swift" 'Every route needs five-layer parity acceptance records.'

route_matrix=$(find "$baselines" -type f -name 'r6-route-*.png' | wc -l | tr -d ' ')
golden_count=$(find "$baselines" -type f -name 'r6-chart*.png' -o -type f -name 'r6-table*.png' | wc -l | tr -d ' ')
if [ "$route_matrix" -ne 62 ]; then
    echo "R6 violation: expected 62 route matrix baselines (31 dark normal + 31 rotated state/width), found $route_matrix."
    exit 1
fi
if [ "$golden_count" -ne 7 ]; then
    echo "R6 violation: expected 7 chart/table golden baselines, found $golden_count."
    exit 1
fi

"$repo_root/apple/scripts/verify-readability-r5.sh"

echo "Readability R6 gate passed. Tables, charts, materials, motion, and acceptance are closed out."
