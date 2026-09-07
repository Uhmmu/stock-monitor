# Readability visual baselines

Goal R1 keeps two complementary screenshot paths:

- `R1/route-*.png`: one normal, standard-width, light, comfortable-density fixture for each of the 31 routes.
- `R1/golden-*.png`: the overview, table, detail/timeline and error-state golden screens plus narrow/wide, dark, compact, empty, partial, stale, loading and permission-denied stress cases.

The fixtures are intentionally de-identified and include long Chinese, long English, missing values, currency units and provenance. They validate the shared presentation grammar without contacting production or changing server authority.

Record baselines:

```sh
STOCK_MONITOR_SNAPSHOT_OUTPUT_DIR="$PWD/apple/Tests/VisualBaselines/R1" \
  swift test --package-path apple/Packages/StockMonitorFeatures \
  --filter readabilitySnapshotHarnessRendersEveryRouteAndGoldenState
```

Compare current rendering with the checked-in baselines:

```sh
swift test --package-path apple/Packages/StockMonitorFeatures \
  --filter readabilitySnapshotHarnessRendersEveryRouteAndGoldenState
```

The macOS UI-test target also captures the same route and stress matrices as XCTest attachments. On machines where XCTest cannot enable Accessibility automation, the off-screen SwiftUI renderer remains the deterministic CI gate; record the UI-run limitation rather than treating it as a product failure.
