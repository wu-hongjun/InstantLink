import SwiftUI

@main
struct InstantLinkApp: App {
    @StateObject private var model = SyncViewModel()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
        }
        .onChange(of: scenePhase) { _, newPhase in
            // Sync is foreground-only in v1: active starts the poll loop,
            // anything else pauses it (plan 050).
            model.scenePhaseChanged(newPhase)
        }
    }
}

struct RootView: View {
    @EnvironmentObject private var model: SyncViewModel

    var body: some View {
        if model.isPaired {
            NavigationStack {
                SyncView()
            }
        } else {
            OnboardingView()
        }
    }
}
