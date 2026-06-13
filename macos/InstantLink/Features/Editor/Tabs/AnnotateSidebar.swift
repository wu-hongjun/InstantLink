import SwiftUI

/// Placeholder sidebar for the Annotate tab; filled in by PR #14.
struct AnnotateSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("editor_tab_annotate"))
                    .font(.headline)
                Text(L("editor_coming_in_pr_14"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}
