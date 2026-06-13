import SwiftUI

/// Photos-style Adjust sidebar — plan 049 rebuild.
///
/// - All-caps `ADJUST` header label at the top.
/// - Sections ordered per plan 047 §2.2 / Photos.app:
///     Light → Color → Black & White → Red Eye → White Balance → Curves →
///     Levels → Definition → Selective Color → Noise Reduction → Sharpen →
///     Vignette.
/// - Bottom `Reset Adjustments` button (disabled when every section is
///   already neutral).
struct AdjustSidebar: View {
    @ObservedObject var state: EditorViewState

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(L_key("editor_adjust_header"))
                .font(.caption.weight(.bold))
                .foregroundStyle(.secondary)
                .padding(.horizontal, 16)
                .padding(.top, 12)
                .padding(.bottom, 8)

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    LightSection(state: state)
                    ColorSection(state: state)
                    BlackAndWhiteSection(state: state)
                    RedEyeSection(state: state)
                    WhiteBalanceSection(state: state)
                    CurvesSection(state: state)
                    LevelsSection(state: state)
                    DefinitionSection(state: state)
                    SelectiveColorSection(state: state)
                    NoiseReductionSection(state: state)
                    SharpenSection(state: state)
                    VignetteSection(state: state)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
            }

            Divider()

            Button {
                state.revert()
            } label: {
                Text(L_key("editor_reset_adjustments"))
                    .font(.callout)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
            }
            .buttonStyle(.borderless)
            .disabled(isAllNeutral)
            .padding(.horizontal, 16)
            .padding(.vertical, 6)
        }
    }

    /// Mirror of `EditorSnapshot.neutral` equality, expressed against the
    /// live `state`. The button only enables when at least one section has
    /// been touched from baseline.
    private var isAllNeutral: Bool {
        state.snapshot() == .neutral
    }
}
