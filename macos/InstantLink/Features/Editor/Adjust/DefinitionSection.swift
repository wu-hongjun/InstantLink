import SwiftUI

/// Photos-style "Definition" panel: single Amount slider + section header
/// with Auto / Reset. Locked decision Q7 — Photos parity (no Radius slider).
struct DefinitionSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = true

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("definition_section"),
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.definition.amount,
                        range: 0...1,
                        neutral: 0,
                        label: L_key("definition_amount"),
                        asymmetric: true
                    )
                }
                .padding(.leading, 18)
            }
        }
    }

    private var isNeutral: Bool {
        state.adjustments.definition.amount == 0
    }

    private func reset() {
        state.adjustments.definition = AdjustmentState.Definition()
    }

    /// Apply a placeholder Auto preset. PR #16 wires the Apple analyzer
    /// (`CIImage.autoAdjustmentFilters`) end-to-end across all sections;
    /// for v1 we set a gentle midtone-contrast boost.
    // TODO: wire Apple analyzer in PR #16 Auto buttons.
    private func applyAuto() {
        if isNeutral {
            state.adjustments.definition.amount = 0.25
        } else {
            // Photos toggles Auto off when clicked a second time.
            reset()
        }
    }
}

// `L_key(_:)` is provided by `LocalizedKey.swift` (hoisted in PR #4).
