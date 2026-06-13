import SwiftUI

/// Photos-style "Selective Color" panel — plan 048 PR #10.
///
/// Locked decision Q6 (audit doc 047 §6): 6 user-defined wells, NOT the
/// 8 fixed colour chips Lightroom ships. Each well stores its own seed
/// colour (set via eyedropper or SwiftUI ColorPicker) plus Hue /
/// Saturation / Luminance / Range deltas. Empty wells (no seed) are
/// ignored by `SelectiveColorKernel`.
///
/// The strip of 6 swatches sits above a sliders block that follows the
/// currently-selected well. The first well with a seed is selected on
/// first interaction; otherwise the user picks via the swatch tap.
struct SelectiveColorSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false
    @State private var selectedWell: Int = 0

    // Plan 049 M4 — Selective Color intentionally ships without an Auto
    // button. `CIImage.autoAdjustmentFilters` returns no per-well selective
    // color suggestion, so there is nothing to seed.

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("sel_section"),
                systemImage: "swatchpalette",
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 10) {
                    wellStrip
                    sliders
                }
                .padding(.leading, 18)
            }
        }
    }

    // MARK: - Well strip

    private var wellStrip: some View {
        HStack(spacing: 6) {
            ForEach(0..<AdjustmentState.SelectiveColor.maxWells, id: \.self) { idx in
                SelectiveColorWellRow(
                    state: state,
                    wellIndex: idx,
                    isSelected: idx == clampedSelected,
                    onSelect: { selectedWell = idx }
                )
            }
        }
    }

    // MARK: - Sliders (track selected well)

    private var sliders: some View {
        let idx = clampedSelected
        return VStack(spacing: 6) {
            AdjustmentSlider(
                value: wellBinding(idx, \.hue),
                range: -1...1,
                neutral: 0,
                label: L_key("sel_hue")
            )
            AdjustmentSlider(
                value: wellBinding(idx, \.saturation),
                range: -1...1,
                neutral: 0,
                label: L_key("sel_saturation")
            )
            AdjustmentSlider(
                value: wellBinding(idx, \.luminance),
                range: -1...1,
                neutral: 0,
                label: L_key("sel_luminance")
            )
            AdjustmentSlider(
                value: wellBinding(idx, \.range),
                range: 0...1,
                neutral: 0.5,
                label: L_key("sel_range")
            )
        }
        .disabled(!wellHasSeed(idx))
        .opacity(wellHasSeed(idx) ? 1 : 0.5)
    }

    // MARK: - Helpers

    private var clampedSelected: Int {
        max(0, min(selectedWell, AdjustmentState.SelectiveColor.maxWells - 1))
    }

    private func wellHasSeed(_ idx: Int) -> Bool {
        guard idx < state.adjustments.selective.wells.count else { return false }
        return state.adjustments.selective.wells[idx].seed != nil
    }

    private func wellBinding(_ idx: Int, _ keyPath: WritableKeyPath<AdjustmentState.SelectiveColor.Well, Double>) -> Binding<Double> {
        Binding(
            get: {
                guard idx < state.adjustments.selective.wells.count else { return 0 }
                return state.adjustments.selective.wells[idx][keyPath: keyPath]
            },
            set: { newValue in
                guard idx < state.adjustments.selective.wells.count else { return }
                state.adjustments.selective.wells[idx][keyPath: keyPath] = newValue
            }
        )
    }

    private var isNeutral: Bool {
        let sel = state.adjustments.selective
        let defaultWell = AdjustmentState.SelectiveColor.Well()
        return sel.wells.allSatisfy { well in
            well.seed == nil
                && well.hue == defaultWell.hue
                && well.saturation == defaultWell.saturation
                && well.luminance == defaultWell.luminance
                && well.range == defaultWell.range
        }
    }

    private func reset() {
        state.adjustments.selective = AdjustmentState.SelectiveColor()
        selectedWell = 0
    }
}
