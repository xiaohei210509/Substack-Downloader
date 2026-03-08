// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "SubstackStudio",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(
            name: "SubstackStudio",
            targets: ["SubstackStudioApp"]
        )
    ],
    targets: [
        .executableTarget(
            name: "SubstackStudioApp",
            path: "Sources/SubstackStudioApp"
        )
    ]
)
