import AppKit
import Combine
import CoreImage
import SwiftUI

/// Shared histogram strip used by Light / Curves / Levels backdrops.
///
/// Wraps `CIAreaHistogram → CIHistogramDisplayFilter` from research 047 §5
/// behind a 100 ms throttle on the editor's preview image so it doesn't
/// spike every slider tick.
struct HistogramView: View {
    @ObservedObject var state: EditorViewState
    @StateObject private var generator = HistogramImageGenerator()

    /// Height the histogram strip renders at. Sections that embed the view
    /// override this for their own visual proportions.
    var height: CGFloat = 56
    /// Rounded-rect corner radius applied to the histogram backdrop.
    var cornerRadius: CGFloat = 4

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(Color.black.opacity(0.18))
            .frame(height: height)
            .overlay(
                Group {
                    if let image = generator.image {
                        Image(nsImage: image)
                            .resizable()
                            .interpolation(.medium)
                            .opacity(0.85)
                    }
                }
            )
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius))
            .onAppear { generator.bind(to: state) }
            .onChange(of: state.previewImage) { generator.requestUpdate() }
            .onChange(of: state.adjustments) { generator.requestUpdate() }
    }
}

/// Bridge that subscribes to editor state and throttles histogram renders.
@MainActor
private final class HistogramImageGenerator: ObservableObject {
    @Published var image: NSImage?

    private weak var state: EditorViewState?
    private let context = CIContext(options: [.useSoftwareRenderer: false])
    private var pendingTask: Task<Void, Never>?

    /// Subject-driven 100 ms throttle. Each `requestUpdate()` call coalesces
    /// into one render via debounced Combine sink — mirrors the documented
    /// research path.
    private let pulse = PassthroughSubject<Void, Never>()
    private var cancellable: AnyCancellable?

    func bind(to state: EditorViewState) {
        self.state = state
        if cancellable == nil {
            cancellable = pulse
                .debounce(for: .milliseconds(100), scheduler: DispatchQueue.main)
                .sink { [weak self] in self?.render() }
        }
        pulse.send(())
    }

    func requestUpdate() {
        pulse.send(())
    }

    private func render() {
        guard let state, let source = state.previewImage else {
            image = nil
            return
        }
        let snapshot = state.snapshot()
        let pipeline = state.pipeline
        let ctx = context
        pendingTask?.cancel()
        pendingTask = Task.detached(priority: .utility) { [weak self] in
            let composed = pipeline.compose(source, state: snapshot)
            let extent = composed.extent
            guard !Task.isCancelled, extent.width > 0, extent.height > 0 else { return }
            let area = CIFilter(name: "CIAreaHistogram", parameters: [
                kCIInputImageKey: composed,
                "inputExtent": CIVector(cgRect: extent),
                "inputCount": 256,
                "inputScale": 50.0,
            ])?.outputImage
            guard let area else { return }
            let display = CIFilter(name: "CIHistogramDisplayFilter", parameters: [
                kCIInputImageKey: area,
                "inputHeight": 100.0,
                "inputHighLimit": 1.0,
                "inputLowLimit": 0.0,
            ])?.outputImage
            guard let display else { return }
            let outExtent = display.extent
            guard outExtent.width > 0, outExtent.height > 0,
                  let cg = ctx.createCGImage(display, from: outExtent) else { return }
            let ns = NSImage(cgImage: cg, size: NSSize(width: outExtent.width, height: outExtent.height))
            await MainActor.run { [weak self] in
                self?.image = ns
            }
        }
    }
}
