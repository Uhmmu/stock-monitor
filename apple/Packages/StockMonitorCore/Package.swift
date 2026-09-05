// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "StockMonitorCore",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "StockMonitorCore", targets: ["StockMonitorCore"])],
    dependencies: [.package(url: "https://github.com/swiftlang/swift-testing.git", exact: "0.12.0")],
    targets: [
        .target(name: "StockMonitorCore"),
        .testTarget(
            name: "StockMonitorCoreTests",
            dependencies: ["StockMonitorCore", .product(name: "Testing", package: "swift-testing")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
