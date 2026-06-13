import SwiftUI

/// Placeholder sidebar for the Adjust tab; filled in across PRs #3 – #13.
struct AdjustSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("editor_tab_adjust"))
                    .font(.headline)
                Text(L("editor_coming_in_pr_3"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}
