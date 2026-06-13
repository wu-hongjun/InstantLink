import SwiftUI

/// Vertical list of overlays inside the Annotate tab. Each row is rendered by
/// `OverlayListRow`; the empty state is a single muted caption.
struct OverlayListView: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        if state.overlays.isEmpty {
            Text(L("No overlays yet"))
                .font(.caption)
                .foregroundColor(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 4)
        } else {
            VStack(spacing: 6) {
                ForEach(state.overlays) { overlay in
                    OverlayListRow(state: state, overlay: overlay)
                }
            }
        }
    }
}
