# Stock Monitor for macOS

This directory contains the native SwiftUI app described by Goals M1 through M3 in
`docs/plans/macos-native-app-plan.md`. The Qt client remains unchanged as a
historical experiment and is not linked by this app.

## Product baseline

- Product name: **Stock Monitor**
- Bundle identifier: `com.jiale.StockMonitor`
- Architecture: Apple Silicon (`arm64`) only
- Minimum app deployment target: macOS 26.0
- Distribution priority: Developer ID + notarization, followed by a later Mac
  App Store decision
- Signing: automatic signing with the developer Team supplied locally; no Team
  identifier or signing credential is committed
- Privacy statement: `docs/privacy-macos.md`
- Server boundary: HTTPS only outside explicit Debug loopback URLs

`StockMonitorCore` owns DTOs, REST, authentication, Keychain access, retry and
error policy. `StockMonitorDesign` owns semantic design primitives.
`StockMonitorFeatures` may depend on both, while neither Core nor Design depends
on a feature or app target. Feature code never owns a `URLSession` directly.

## Generate and verify

The Goal M1 baseline is pinned to stable Xcode 26.6. Install and select it before running the full build.
The project itself is reproducibly generated with XcodeGen:

```sh
cd apple
xcodegen generate
swift build -c release --arch arm64
./scripts/build-local-app.sh
./scripts/doctor.sh
swiftformat Apps Packages Tests --lint
swiftlint lint --config .swiftlint.yml
swift test --package-path Packages/StockMonitorCore
swift test --package-path Packages/StockMonitorDesign
swift test --package-path Packages/StockMonitorFeatures
xcodebuild -workspace StockMonitor.xcworkspace -scheme StockMonitorMac \
  -configuration Release -destination 'platform=macOS,arch=arm64' \
  CODE_SIGNING_ALLOWED=NO build
xcodebuild -workspace StockMonitor.xcworkspace -scheme StockMonitorMac \
  -configuration Debug -destination 'platform=macOS,arch=arm64' \
  CODE_SIGN_IDENTITY=- test
```

For a signed foundation archive, set `STOCK_MONITOR_DEVELOPMENT_TEAM` only in the current shell, then run
`./scripts/archive.sh` with a valid Apple Development or Developer ID identity. Never commit
the Team identifier, certificate, provisioning material or notarization secret.

After storing App Store Connect credentials with `xcrun notarytool
store-credentials`, set `STOCK_MONITOR_NOTARY_PROFILE` to that local Keychain
profile and run `./scripts/notarize.sh`. It exports with the `developer-id`
method, submits the zip, staples the accepted ticket, and verifies Gatekeeper.
A paid Apple Developer Program membership and a Developer ID Application
certificate are required for that distribution step.

`scripts/build-local-app.sh` creates an ad-hoc signed local bundle under the
ignored `DerivedData/` directory. It verifies bundle layout, AppIcon, hardened
runtime and sandbox entitlements without claiming Developer ID distribution.
The Xcode UI test target captures the ready-state baseline and verifies stable
accessibility identifiers; it runs once the full Xcode toolchain is selected.

## Configuration

Debug points only at `http://127.0.0.1:8000`. Staging and Production use HTTPS.
The runtime configuration validator rejects plain HTTP for every non-loopback
host, including in Debug builds.

The client stores only the refresh token in Keychain. The access token stays in
the `AuthSession` actor's memory. Logout clears local credentials even if the
server is unreachable. The app does not persist AI or IBKR private content.

## Goal M2 application shell

The shared native shell provides grouped `NavigationSplitView` routing for every planned
feature, role-filtered administrator routes, Command-K search, customizable toolbars,
restorable main/detail windows, inspectors, deep links and system context menus. Business
screens outside Goal M3 remain placeholders until their corresponding M4-M5 goals.

## Goal M3 daily monitoring

Goal M3 replaces the Overview, Watchlist, Alerts, News, Investment Calendar and Reports
placeholders with authenticated native workflows. Overview restores REST snapshots before a
single merged market SSE, includes the portfolio benchmark, and keeps source/stale/market-session
state visible. Watchlist uses server-resolved Security identities for search, grouping, reorder,
thresholds, alert controls, peer management and undoable removal. Content lists use bounded
pagination, preserve last-good data on failure, render Markdown without arbitrary HTML execution,
and confirm the destination domain before opening an external article.

`StockMonitorCore` includes the memory-first last-good resource store, bounded read-only disk
cache, one-process market SSE coordinator, chunk-safe SSE parser, AI stream state machine,
active-only job polling policy and redacted metrics. `StockMonitorDesign` includes compact and
comfortable density, semantic state components, motion tokens and an interactive Design Lab.
