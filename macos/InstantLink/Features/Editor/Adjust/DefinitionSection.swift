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

    /// Apply Auto via `AutoEnhance.apply(target: .definition, …)`. The Apple
    /// analyzer doesn't surface a definition-specific filter, so the helper
    /// sets a gentle midtone-contrast preset. Toggles back to neutral on a
    /// second click.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .definition, image: image, state: state)
    }
}

// `L_key(_:)` is provided by `LocalizedKey.swift` (hoisted in PR #4).
