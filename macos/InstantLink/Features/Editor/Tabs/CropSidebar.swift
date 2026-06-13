import SwiftUI

/// Placeholder sidebar for the Crop tab; filled in by PR #2.
struct CropSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text(L("editor_tab_crop"))
                    .font(.headline)
                Text(L("editor_coming_in_pr_2"))
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(20)
        }
    }
}
