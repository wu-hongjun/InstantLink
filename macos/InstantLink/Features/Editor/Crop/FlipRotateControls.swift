import AppKit
import SwiftUI

/// Single Flip button (plain click = horizontal, Option-click = vertical)
/// plus Rotate 90° (plain click = CCW, Option-click = CW). Mirrors the
/// Photos Crop sidebar layout.
struct FlipRotateControls: View {
    @Binding var crop: CropState

    var body: some View {
        HStack(spacing: 8) {
            Button {
                if NSEvent.modifierFlags.contains(.option) {
                    crop.flipVertical.toggle()
                } else {
                    crop.flipHorizontal.toggle()
                }
            } label: {
                Label(L("crop_flip"), systemImage: "arrow.left.and.right.righttriangle.left.righttriangle.right")
                    .labelStyle(.iconOnly)
                    .frame(minWidth: 28, minHeight: 22)
            }
            .help(L("crop_flip"))

            Button {
                if NSEvent.modifierFlags.contains(.option) {
                    // Clockwise = subtract one quarter.
                    crop.rotate90Quarter = ((crop.rotate90Quarter - 1) % 4 + 4) % 4
                } else {
                    crop.rotate90Quarter = (crop.rotate90Quarter + 1) % 4
                }
            } label: {
                Label(L("crop_rotate_90"), systemImage: "rotate.left")
                    .labelStyle(.iconOnly)
                    .frame(minWidth: 28, minHeight: 22)
            }
            .help(L("crop_rotate_90"))
        }
    }
}
