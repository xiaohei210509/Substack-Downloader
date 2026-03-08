import SwiftUI

@main
struct SubstackStudioApp: App {
    @StateObject private var viewModel = AppViewModel()

    var body: some Scene {
        WindowGroup {
            ContentView(viewModel: viewModel)
                .frame(minWidth: 1180, minHeight: 760)
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1240, height: 820)

        Settings {
            SettingsView(viewModel: viewModel)
                .padding(24)
                .frame(width: 560, height: 420)
        }
    }
}
