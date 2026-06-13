import SwiftUI

/// Right-side panel for the Crop tab (plan 048 PR #2).
///
/// Layout (top → bottom): three sliders (Straighten / Vertical / Horizontal),
/// the Aspect picker + orientation toggle inline with Flip + Rotate-90°, the
/// Auto button (currently a no-op placeholder for v1; Vision horizon detection
/// lands in the polish PR #17), and the Reset button.
struct CropSidebar: View {
    @ObservedObject var state: EditorViewState
    @EnvironmentObject var viewModel: ViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                slidersSection
                Divider()
                aspectAndFlipSection
                Divider()
                autoButton
                Spacer(minLength: 8)
                resetButton
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    // MARK: - Sections

    private var slidersSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            StraightenSlider(
                value: $state.crop.straightenDegrees,
                range: -45...45,
                neutral: 0,
                label: L("crop_straighten"),
                unit: "°",
                snapThreshold: 0.5
            )
            StraightenSlider(
                value: $state.crop.verticalSkew,
                range: -1...1,
                neutral: 0,
                label: L("crop_vertical"),
                snapThreshold: 0.02
            )
            StraightenSlider(
                value: $state.crop.horizontalSkew,
                range: -1...1,
                neutral: 0,
                label: L("crop_horizontal"),
                snapThreshold: 0.02
            )
        }
    }

    private var aspectAndFlipSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .center, spacing: 12) {
                AspectRatioPicker(
                    crop: $state.crop,
                    printerAvailable: viewModel.selectedPrinter != nil
                )
                .layoutPriority(1)
                Spacer(minLength: 0)
                FlipRotateControls(crop: $state.crop)
            }
        }
    }

    private var autoButton: some View {
        // TODO: Vision horizon detection (PR #17 polish). For v1 this is a
        // no-op placeholder so the UI layout matches Photos.
        Button {
            // No-op for v1; horizon detection lands in PR #17.
        } label: {
            Label(L("crop_auto"), systemImage: "wand.and.stars")
                .frame(maxWidth: .infinity)
        }
        .controlSize(.regular)
    }

    private var resetButton: some View {
        Button {
            resetCrop()
        } label: {
            Label(L("crop_reset"), systemImage: "arrow.counterclockwise")
                .frame(maxWidth: .infinity)
        }
        .controlSize(.regular)
    }

    // MARK: - Actions

    private func resetCrop() {
        // Reset clears Crop + Straighten + V + H + Flip, but does not touch
        // Adjust-tab state (per Photos semantics).
        state.crop = .neutral
    }
}
