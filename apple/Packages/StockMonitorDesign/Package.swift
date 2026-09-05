// swift-tools-version: 6.2
import PackageDescription

let package = Package(
    name: "StockMonitorDesign",
    platforms: [.macOS(.v14), .iOS(.v17)],
    products: [.library(name: "StockMonitorDesign", targets: ["StockMonitorDesign"])],
    dependencies: [.package(url: "https://github.com/swiftlang/swift-testing.git", exact: "0.12.0")],
    targets: [
        .target(name: "StockMonitorDesign"),
        .testTarget(
            name: "StockMonitorDesignTests",
            dependencies: ["StockMonitorDesign", .product(name: "Testing", package: "swift-testing")]
        ),
    ],
    swiftLanguageModes: [.v6]
)
