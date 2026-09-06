# Stock Monitor for macOS

This directory contains the native SwiftUI app described by Goals M1 through M6 in
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

`./scripts/verify-goal-m6.sh` is the reproducible arm64 quality gate. It validates the
Web-to-Mac parity inventory, privacy manifest, formatting/lint, Swift and selected backend
contracts, local app bundle, unsigned Release build and accessibility UI smoke test.
`./scripts/build-release-candidate.sh` creates a checksummed, ad-hoc signed local DMG that is
explicitly not a public distribution artifact. `./scripts/distribution-status.sh` reports the
remaining Developer ID/notarization gate without reading or printing credentials.

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
screens outside Goal M3 are implemented by their corresponding M4-M5 workspaces.

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

## Goal M4 research workbench

Goal M4 replaces the company-research, technical-chart and market-intelligence placeholders
with native workflows over the existing authenticated REST contracts. `ResearchWorkspaceService`
is the single data boundary for M4; flexible server payloads (valuation snapshots, mood evidence,
industry metadata) stay as retained JSON instead of being recomputed client-side.

- Company research: fundamentals with per-metric source support, quarterly key figures, Yahoo
  three-statement snapshots, the daily cross-model valuation snapshot, Historical P/E with
  statistics and reference lines, Graham override recalculation, all five SEC datasets
  (filings/events/financials/insider/13F), public-figure portfolios and trade timelines, and the
  2–6 symbol deterministic comparison with ranking, winners, history series and limitations.
- Technical analysis: native Swift Charts candlestick rendering with volume sub-chart, MA
  overlays, swing support/resistance, Fibonacci retracement, two-point trend lines, event
  markers, portfolio cost line and price-alert lines. Drag pans, pinch zooms, hover shows the
  crosshair tooltip, and a non-visual data summary keeps the chart accessible. Price alerts are
  created and deleted through the authenticated server endpoints.
- Market intelligence: US macro overview/series/yield-curve/sync-status, industry pulse overview,
  AI chain taxonomy, focus signals and system status, options rankings with chain and IV history,
  AI mood console with history health, and the admin Mood Lab (run start with active-only
  backoff polling, results, and guarded EOD history recovery).

## Goal M5 high-risk workflows

Goal M5 replaces the AI, portfolio, IBKR, Crypto, journal, settings and administration
placeholders with authenticated native workspaces. `GoalM5Service` is their only transport
boundary. Flexible server results remain lossless JSON for forward compatibility and are
presented as native list/detail content without executing HTML or JavaScript.

- AI Chat supports conversation history, rich-message snapshots, model and search modes,
  chunk-safe streaming, tool activity, citations, stop, Deep Search confirmation and
  server-truth recovery after interruption.
- Portfolio and journal views expose the server-calculated multi-currency summary,
  positions, transactions, lots, completed trades, performance, attribution, benchmark,
  health, strategy profile, interpretation and asynchronous analysis history.
- IBKR screens are read-only account/research surfaces plus explicit server-side syncs.
  The app contains no IBKR credential or proxy setting and cannot bypass server policy.
- Crypto research, quant/backtest and internal PAPER screens expose persisted identity,
  market, derivatives, research, signal, run, order, fill, ledger and reconciliation state.
  There is no Binance Demo/Testnet/Live or real-order control surface.
- Destructive or paid operations use a scoped confirmation, role-gated endpoints remain
  hidden from ordinary users, and valid content stays visible while a refresh fails.

## Goal M6 closure and release readiness

The checked-in parity catalog accounts for every native route and ties it to the corresponding
Web surface. The public `/api/client-capabilities` handshake enforces the minimum supported Mac
version and required server capabilities; a missing endpoint remains visibly usable only for the
legacy rollout window. Support diagnostics are user-initiated and privacy-scoped.

The app includes an explicit Privacy Manifest, release notes, release checklist, deterministic
arm64 local candidate packaging and a single automated verification entry point. Same-account
Web/Mac golden flows, Instruments/assistive-technology evidence and clean-device soak results stay
marked runtime-pending until actually executed. Developer ID signing, Apple notarization,
stapling and public Gatekeeper validation remain blocked until a paid Apple Developer Program
membership is available; an ad-hoc local candidate must never be described as notarized.
