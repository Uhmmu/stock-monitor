// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "StockMonitorApple",
    platforms: [.macOS("26.0")],
    products: [
        .executable(name: "StockMonitorMac", targets: ["StockMonitorMac"]),
    ],
    dependencies: [
        .package(path: "Packages/StockMonitorCore"),
        .package(path: "Packages/StockMonitorFeatures"),
    ],
    targets: [
        .executableTarget(
            name: "StockMonitorMac",
            dependencies: [
                .product(name: "StockMonitorCore", package: "StockMonitorCore"),
                .product(name: "StockMonitorFeatures", package: "StockMonitorFeatures"),
            ],
            path: "Apps/StockMonitorMac",
            exclude: ["Assets.xcassets", "Info.plist", "StockMonitorMac.entitlements"]
        ),
    ],
    swiftLanguageModes: [.v6]
)
