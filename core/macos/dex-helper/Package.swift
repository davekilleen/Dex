// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "DexHelper",
    platforms: [
        .macOS(.v14),
    ],
    products: [
        .executable(name: "DexHelper", targets: ["DexHelperApp"]),
    ],
    targets: [
        .target(
            name: "DexHelper",
            path: "Sources/DexHelper",
            linkerSettings: [
                .linkedFramework("EventKit"),
                .linkedFramework("AppKit"),
            ]
        ),
        .executableTarget(
            name: "DexHelperApp",
            dependencies: ["DexHelper"],
            path: "Sources/DexHelperApp"
        ),
        .testTarget(
            name: "DexHelperTests",
            dependencies: ["DexHelper"],
            path: "Tests/DexHelperTests"
        ),
    ]
)
