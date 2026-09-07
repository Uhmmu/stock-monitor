# Goal R1 readability baseline evidence

Date: 2026-09-08

## Scope

- 31/31 routes are represented by `ReadabilityAuditCatalog` with user task, primary information, primary action, evidence, failure state, severity and seven audit aspects.
- All 12 M5 routes that currently depend on generic object/JSON presentation are P0 by executable test, so field presence cannot be counted as readability completion.
- 31 normal route baselines and 7 golden/stress baselines are stored under `Tests/VisualBaselines/R1`.

## Coverage matrix

| Dimension | Covered values |
| --- | --- |
| Window | narrow, standard, wide |
| Appearance | light, dark |
| Density | comfortable, compact |
| Resource state | normal, empty, partial, stale, loading, error, permission denied |
| Stress content | long Chinese, long English, tabular financial figures, large amounts, missing values, source and freshness |

## Design language

- Six text roles: page title, section title, body, metric label, metadata and micro annotation.
- Complete spacing scale, readable/standard/wide content widths, surfaces, separators, corners, elevation, control/row dimensions, chart palette and semantic statuses.
- Financial formatting covers price, abbreviated amount, percentage, multiple, date/time, currency, sign, non-finite/missing, estimate, stale, not applicable, not collected and provider failure.
- Compact density changes row/control/padding rhythm without shrinking semantic body text.

## Shared components

`PageScaffold`, `PageHeader`, `SectionHeader`, `MetricHero`, `MetricGrid`, `MetadataStrip`, `SourceBadge`, `FreshnessBadge`, `CoverageBadge`, `EmptyState`, `InlineError`, `DisclosureSection`, `FinancialTable`, `ComparisonTable`, `TimelineList`, `EvidencePanel`, `ChartContainer` and `ActionBar` are available from `StockMonitorDesign` and exposed in Design Lab.

## Verification

- `StockMonitorDesign`: 4 tests passed.
- `StockMonitorFeatures`: 41 tests passed after adding the snapshot test.
- Root Apple arm64 release build and unsigned Xcode `build-for-testing` passed.
- Off-screen renderer generated and byte-compared 38 PNG files; three representative images were manually inspected after fixing transparent-canvas and unattached-window defects.
- Native XCTest UI automation could not initialize because macOS timed out while enabling automation mode. Result bundle: `~/Library/Developer/Xcode/DerivedData/StockMonitor-*/Logs/Test/Test-StockMonitorMac-2026.09.08_02-37-34-+0800.xcresult`. This is a system test-runner limitation; the UI-test matrix compiles, while the deterministic renderer supplies the current visual gate.

## R1 exit assessment

- R1.0: met through the executable 31-route audit catalog, stored screenshots and severity gate.
- R1.1: met through shared tokens, semantic content roles, density profiles, financial formatters and the no-new-literals guard.
- R1.2: met through reusable semantic/data components, accessibility identifiers, logic tests, four representative golden screen families and deterministic image comparison.
