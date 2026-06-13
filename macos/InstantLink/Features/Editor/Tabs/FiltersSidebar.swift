import SwiftUI

/// Right-side panel for the Filters tab (plan 048 PR #15).
///
/// Hosts the vertical filter thumbnail strip (`FilterRail`) tab-gated to the
/// Filters tab per locked decision Q2. When a B&W filter is selected it
/// overrides the Adjust B&W stack in the pipeline (locked decision Q9).
struct FiltersSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L("filters_section"))
                .font(.headline)
                .padding(.horizontal, 20)
                .padding(.top, 16)
                .padding(.bottom, 8)
            FilterRail(state: state)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}
