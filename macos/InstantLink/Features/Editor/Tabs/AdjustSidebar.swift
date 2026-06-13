import SwiftUI

/// Host for all Adjust panels. Subsequent PRs append their section views
/// to the same scrollable VStack.
struct AdjustSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                LightSection(state: state)
                // PR #4: ColorSection(state: state)
                // PR #5: CurvesSection / LevelsSection / HistogramView
                // PR #6: VignetteSection
                // PR #7: SharpenSection
                // PR #8: NoiseReductionSection
                // PR #9: DefinitionSection
                // PR #10: SelectiveColorSection
                // PR #11: RedEyeSection
                // PR #12: WhiteBalanceSection
                // PR #13: BlackAndWhiteSection
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
        }
    }
}
