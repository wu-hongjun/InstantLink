import CoreGraphics
import CoreImage
import SwiftUI
import Vision

/// Photos-style "Red Eye" panel.
///
/// - Size slider drives the per-correction radius for newly-appended records
///   (asymmetric 4…96 px, neutral 24).
/// - Auto button runs `VNDetectFaceLandmarksRequest` over the source image
///   and appends a correction at each detected eye center.
/// - Pick Eyes button toggles the shared `EyedropperManager` into the
///   `.redEyeManual` (position-only) mode. The next canvas click appends a
///   `RedEyeCorrection` at the click position via PR #12 plumbing.
/// - List of current corrections with per-row delete buttons.
struct RedEyeSection: View {
    @ObservedObject var state: EditorViewState
    @State private var isExpanded: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            AdjustmentSectionHeader(
                isExpanded: $isExpanded,
                title: L_key("redeye_section"),
                systemImage: "eye.slash",
                onAuto: { applyAuto() },
                onReset: { reset() },
                isNeutral: isNeutral
            )

            if isExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    AdjustmentSlider(
                        value: $state.adjustments.redEye.size,
                        range: 4...96,
                        neutral: 24,
                        label: L_key("redeye_size"),
                        asymmetric: true
                    )

                    HStack(spacing: 8) {
                        Button {
                            Task { await autoDetect() }
                        } label: {
                            Label(L_key("redeye_auto_detect"), systemImage: "wand.and.stars")
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)

                        Button {
                            togglePickEyes()
                        } label: {
                            Label(L_key("redeye_pick_eyes"), systemImage: pickEyesSystemImage)
                        }
                        .buttonStyle(.borderless)
                        .controlSize(.small)

                        if !state.adjustments.redEye.corrections.isEmpty {
                            Spacer()
                            Button(L_key("redeye_clear")) { clearCorrections() }
                                .buttonStyle(.borderless)
                                .controlSize(.small)
                        }
                    }

                    if !state.adjustments.redEye.corrections.isEmpty {
                        VStack(alignment: .leading, spacing: 4) {
                            ForEach(Array(state.adjustments.redEye.corrections.enumerated()), id: \.offset) { idx, c in
                                HStack {
                                    Text(String(
                                        format: "(%d, %d) · r=%d",
                                        Int(c.point.x.rounded()),
                                        Int(c.point.y.rounded()),
                                        Int(c.radius.rounded())
                                    ))
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                                    Spacer()
                                    Button {
                                        delete(at: idx)
                                    } label: {
                                        Image(systemName: "xmark.circle.fill")
                                            .foregroundStyle(.secondary)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                        }
                        .padding(.top, 4)
                    }
                }
                .padding(.leading, 18)
            }
        }
    }

    // MARK: - Auto (analyzer-driven)

    /// Wire the section header's Auto button to `AutoEnhance.apply(.redEye)`,
    /// which runs the CoreImage analyzer's CIRedEyeCorrection filter. On a
    /// second click (already non-neutral) we reset to match Photos' toggle
    /// behavior. The dedicated "Auto Detect" button below still runs the
    /// Vision face-landmarks pathway for higher-quality matches.
    private func applyAuto() {
        if !isNeutral {
            reset()
            return
        }
        guard let image = state.sourceImage ?? state.previewImage else { return }
        AutoEnhance.apply(target: .redEye, image: image, state: state)
    }

    // MARK: - Neutral / reset

    private var isNeutral: Bool {
        let r = state.adjustments.redEye
        return r.corrections.isEmpty && r.size == 24
    }

    private func reset() {
        state.adjustments.redEye = AdjustmentState.RedEye()
        if state.eyedropperManager.active == .redEyeManual {
            state.eyedropperManager.cancel()
        }
    }

    private func clearCorrections() {
        state.adjustments.redEye.corrections.removeAll()
    }

    private func delete(at index: Int) {
        guard state.adjustments.redEye.corrections.indices.contains(index) else { return }
        state.adjustments.redEye.corrections.remove(at: index)
    }

    // MARK: - Pick Eyes (manual click-to-fix)

    private var pickEyesSystemImage: String {
        state.eyedropperManager.active == .redEyeManual
            ? "scope"
            : "hand.point.up.left.fill"
    }

    private func togglePickEyes() {
        if state.eyedropperManager.active == .redEyeManual {
            state.eyedropperManager.cancel()
            return
        }
        state.eyedropperManager.startPoint(.redEyeManual) { [weak state] point in
            guard let state else { return }
            let radius = state.adjustments.redEye.size
            state.adjustments.redEye.corrections.append(
                AdjustmentState.RedEyeCorrection(point: point, radius: radius)
            )
        }
    }

    // MARK: - Auto Detect (Vision-driven)

    /// Run `VNDetectFaceLandmarksRequest` over the editor's source image and
    /// append a correction record at each detected eye center. Uses the
    /// pupil landmark when available, falling back to the eye-region centroid.
    /// Image-space coordinates are CIImage y-up (matches `RedEyeCorrection`
    /// records appended via the manual pathway).
    @MainActor
    private func autoDetect() async {
        guard let ciImage = state.sourceImage ?? state.previewImage else { return }
        let context = CIContext()
        let extent = ciImage.extent
        guard extent.width > 0, extent.height > 0,
              let cgImage = context.createCGImage(ciImage, from: extent) else {
            return
        }

        let request = VNDetectFaceLandmarksRequest()
        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        do {
            try handler.perform([request])
        } catch {
            return
        }
        guard let observations = request.results else { return }

        let radius = state.adjustments.redEye.size
        let imageWidth = CGFloat(cgImage.width)
        let imageHeight = CGFloat(cgImage.height)
        var appended: [AdjustmentState.RedEyeCorrection] = []
        for face in observations {
            if let leftPoint = eyePoint(
                pupil: face.landmarks?.leftPupil,
                eye: face.landmarks?.leftEye,
                boundingBox: face.boundingBox,
                imageWidth: imageWidth,
                imageHeight: imageHeight
            ) {
                appended.append(.init(point: leftPoint, radius: radius))
            }
            if let rightPoint = eyePoint(
                pupil: face.landmarks?.rightPupil,
                eye: face.landmarks?.rightEye,
                boundingBox: face.boundingBox,
                imageWidth: imageWidth,
                imageHeight: imageHeight
            ) {
                appended.append(.init(point: rightPoint, radius: radius))
            }
        }
        if !appended.isEmpty {
            state.adjustments.redEye.corrections.append(contentsOf: appended)
        }
    }

    /// Resolve a single eye's image-space center. Prefers the pupil landmark;
    /// falls back to the eye-region centroid. Returns nil when neither is
    /// available.
    private func eyePoint(
        pupil: VNFaceLandmarkRegion2D?,
        eye: VNFaceLandmarkRegion2D?,
        boundingBox: CGRect,
        imageWidth: CGFloat,
        imageHeight: CGFloat
    ) -> CGPoint? {
        let region = pupil ?? eye
        guard let region else { return nil }
        let points = region.normalizedPoints
        guard !points.isEmpty else { return nil }
        let sum = points.reduce(into: CGPoint.zero) { acc, p in
            acc.x += CGFloat(p.x)
            acc.y += CGFloat(p.y)
        }
        let count = CGFloat(points.count)
        let centroid = CGPoint(x: sum.x / count, y: sum.y / count)
        return denormalize(
            normalized: centroid,
            faceBox: boundingBox,
            imageWidth: imageWidth,
            imageHeight: imageHeight
        )
    }

    /// Vision landmark points come in face-bounding-box-relative coordinates
    /// with y-up convention. Map them back to CIImage pixel-space (y-up).
    private func denormalize(
        normalized: CGPoint,
        faceBox: CGRect,
        imageWidth: CGFloat,
        imageHeight: CGFloat
    ) -> CGPoint {
        // First map landmark from face-box-relative back to normalized image
        // coordinates, then scale by image dimensions.
        let nx = faceBox.origin.x + normalized.x * faceBox.width
        let ny = faceBox.origin.y + normalized.y * faceBox.height
        return CGPoint(x: nx * imageWidth, y: ny * imageHeight)
    }
}
