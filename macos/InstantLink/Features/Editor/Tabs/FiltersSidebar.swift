import SwiftUI

/// Placeholder sidebar for the Filters tab; filled in by PR #15.
struct FiltersSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("editor_tab_filters"))
                    .font(.headline)
                Text(L("editor_coming_in_pr_15"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}
