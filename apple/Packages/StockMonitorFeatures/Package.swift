// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "StockMonitorFeatures",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "StockMonitorFeatures", targets: ["StockMonitorFeatures"])],
    dependencies: [
        .package(path: "../StockMonitorCore"),
        .package(path: "../StockMonitorDesign"),
        .package(url: "https://github.com/swiftlang/swift-testing.git", exact: "0.12.0"),
    ],
    targets: [
        .target(
            name: "StockMonitorFeatures",
            dependencies: ["StockMonitorCore", "StockMonitorDesign"]
        ),
        .testTarget(
            name: "StockMonitorFeaturesTests",
            dependencies: ["StockMonitorFeatures", .product(name: "Testing", package: "swift-testing")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
