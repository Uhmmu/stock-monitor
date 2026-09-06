# Third-party notices

The Stock Monitor macOS application target links only Apple system frameworks and the project's
local `StockMonitorCore`, `StockMonitorDesign` and `StockMonitorFeatures` packages. The verified
arm64 candidate contains no embedded third-party framework or dynamic library.

Development and tests resolve these packages:

- Swift Testing 0.12.0 — Copyright Apple Inc. and the Swift project authors; Apache License 2.0.
- Swift Syntax 600.0.1 — Copyright Apple Inc. and the Swift project authors; Apache License 2.0.

They are build/test dependencies and are not shipped as embedded frameworks in the application
bundle. Exact revisions are pinned in each package's `Package.resolved`. Apple system frameworks
are provided by macOS and are governed by Apple's applicable software license agreements.
