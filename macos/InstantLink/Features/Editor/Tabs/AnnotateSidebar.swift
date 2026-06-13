import SwiftUI

/// Annotate sidebar — 4th tab of the Photos-style editor (plan 048 PR #14).
/// Hosts the overlay add palette, the overlay list, and the inspector for
/// the selected overlay.
struct AnnotateSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                OverlayAddPalette(state: state)
                OverlayListView(state: state)
                if state.selectedOverlay != nil {
                    OverlayInspectorView(state: state)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}
