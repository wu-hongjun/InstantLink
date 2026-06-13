import SwiftUI

/// Host for all Adjust panels. Subsequent PRs append their section views
/// to the same scrollable VStack.
struct AdjustSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                LightSection(state: state)
                ColorSection(state: state)
                CurvesSection(state: state)
                LevelsSection(state: state)
                DefinitionSection(state: state)
                NoiseReductionSection(state: state)
                SharpenSection(state: state)
                // PR #10: SelectiveColorSection
                // PR #11: RedEyeSection
                WhiteBalanceSection(state: state)
                // PR #13: BlackAndWhiteSection
                // Vignette runs last in the pipeline composition; mirror
                // that ordering in the sidebar so it sits at the bottom
                // of the Adjust list (PR #6 of plan 048).
                VignetteSection(state: state)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
    }
}
