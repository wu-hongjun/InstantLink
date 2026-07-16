import AVFoundation
import SwiftUI

/// Pairing flow: scan the QR on the Bridge LCD, then watch the join /
/// discover / paired steps complete. Also presented as a sheet from Settings
/// for re-pairing.
struct OnboardingView: View {
    @EnvironmentObject private var model: SyncViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var isEnteringLinkManually = false
    @State private var manualLink = ""

    var body: some View {
        VStack(spacing: 0) {
            switch model.onboardingStep {
            case .scanning:
                scannerSection
            case .joiningNetwork, .discovering:
                PairingProgressView(step: model.onboardingStep)
            case .manualJoinNeeded(let ssid, let psk):
                manualJoinSection(ssid: ssid, psk: psk)
            case .paired(let deviceID):
                pairedSection(deviceID: deviceID)
            case .failed(let message):
                failedSection(message)
            }
        }
        .background(Color(.systemBackground))
    }

    // MARK: - Scanner

    private var scannerSection: some View {
        ZStack {
            QRScannerView { code in
                Task { await model.completePairing(scannedCode: code) }
            }
            .ignoresSafeArea()

            VStack {
                VStack(spacing: 10) {
                    BrandMark(size: 48)
                    Text("Pair with your Bridge")
                        .font(.title2.bold())
                    Text("On the Bridge, open Settings ▸ Network ▸ iPhone pairing, then scan the QR code on its screen.")
                        .font(.subheadline)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                }
                .padding(20)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
                .padding()

                Spacer()

                RoundedRectangle(cornerRadius: 24)
                    .strokeBorder(.white.opacity(0.8), lineWidth: 3)
                    .frame(width: 240, height: 240)

                Spacer()

                // Fallback for when the camera can't scan (e.g. a broken
                // camera): the pairing link drives the exact same pipeline
                // as a scanned QR code.
                Button("Enter pairing link instead") {
                    manualLink = ""
                    isEnteringLinkManually = true
                }
                .font(.subheadline.weight(.medium))
                .padding(.vertical, 10)
                .padding(.horizontal, 16)
                .background(.thinMaterial, in: Capsule())
                .padding(.bottom, 24)
            }
        }
        .alert("Enter pairing link", isPresented: $isEnteringLinkManually) {
            TextField("instantlink://pair?…", text: $manualLink)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Pair") {
                let link = manualLink.trimmingCharacters(in: .whitespacesAndNewlines)
                Task { await model.completePairing(scannedCode: link) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("If scanning isn't possible, paste the Bridge's pairing link — the same instantlink://pair address its QR code encodes.")
        }
    }

    // MARK: - Manual network join

    /// Shown when the in-app hotspot join is unavailable (free personal
    /// signing teams can't hold the Hotspot Configuration entitlement) or
    /// fails: the user joins the Bridge Wi-Fi in iOS Settings using the
    /// credentials from the QR, then resumes pairing.
    private func manualJoinSection(ssid: String, psk: String?) -> some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "wifi")
                .font(.system(size: 56))
                .foregroundStyle(.tint)
            Text("Join the Bridge Wi-Fi")
                .font(.title2.bold())
            Text("This build can't join Wi-Fi for you. Open Settings ▸ Wi-Fi and join the network below, then come back and continue.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)

            VStack(spacing: 8) {
                LabeledContent("Network", value: ssid)
                if let psk {
                    LabeledContent("Password") {
                        Text(psk)
                            .font(.body.monospaced().bold())
                            .textSelection(.enabled)
                    }
                }
            }
            .padding()
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
            .padding(.horizontal, 32)

            Text("iOS may warn that this network has no internet — that's expected; stay joined.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()

            Button {
                Task { await model.continueAfterManualJoin() }
            } label: {
                Text("I've joined — continue")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding(.horizontal)

            Button("Cancel") {
                model.restartOnboarding()
            }
            .padding(.bottom, 24)
        }
    }

    // MARK: - Result states

    private func pairedSection(deviceID: String) -> some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 64))
                .foregroundStyle(.green)
            Text("Paired with \(deviceID)")
                .font(.title2.bold())
            Text("Photos received by the Bridge will sync into your library while this app is open.")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()
            Button {
                model.finishOnboarding()
                dismiss() // No-op when not presented as a sheet.
            } label: {
                Text("Start syncing")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding()
        }
    }

    private func failedSection(_ message: String) -> some View {
        VStack(spacing: 20) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 64))
                .foregroundStyle(.orange)
            Text("Pairing failed")
                .font(.title2.bold())
            Text(message)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()
            Button {
                model.restartOnboarding()
            } label: {
                Text("Scan again")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .padding()
        }
    }
}

// MARK: - Progress steps

private struct PairingProgressView: View {
    let step: SyncViewModel.OnboardingStep

    private enum RowState {
        case pending, active, done
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 24) {
            Spacer()
            row("Join Bridge network", state: joinState)
            row("Find Bridge on the network", state: discoverState)
            row("Paired", state: .pending)
            Spacer()
            Text("The Bridge network has no internet — that's expected while syncing.")
                .font(.footnote)
                .foregroundStyle(.secondary)
                .padding(.bottom, 24)
        }
        .padding(.horizontal, 32)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var joinState: RowState {
        step == .joiningNetwork ? .active : .done
    }

    private var discoverState: RowState {
        step == .discovering ? .active : .pending
    }

    private func row(_ title: String, state: RowState) -> some View {
        HStack(spacing: 12) {
            switch state {
            case .pending:
                Image(systemName: "circle")
                    .foregroundStyle(.tertiary)
            case .active:
                ProgressView()
            case .done:
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
            }
            Text(title)
                .font(.body)
                .foregroundStyle(state == .pending ? .secondary : .primary)
        }
    }
}

// MARK: - QR scanner

/// AVFoundation QR scanner wrapped for SwiftUI. Reports each distinct payload
/// once; the session keeps running so an invalid code can be re-scanned after
/// the failure screen sends the user back.
struct QRScannerView: UIViewControllerRepresentable {
    let onCode: (String) -> Void

    func makeUIViewController(context: Context) -> ScannerViewController {
        let controller = ScannerViewController()
        controller.onCode = onCode
        return controller
    }

    func updateUIViewController(_ controller: ScannerViewController, context: Context) {
        controller.onCode = onCode
    }

    final class ScannerViewController: UIViewController, AVCaptureMetadataOutputObjectsDelegate {
        var onCode: ((String) -> Void)?

        private let session = AVCaptureSession()
        private let sessionQueue = DispatchQueue(label: "QRScannerView.session")
        private var previewLayer: AVCaptureVideoPreviewLayer?
        private var lastPayload: String?

        override func viewDidLoad() {
            super.viewDidLoad()
            view.backgroundColor = .black
            configureSession()
        }

        override func viewWillAppear(_ animated: Bool) {
            super.viewWillAppear(animated)
            lastPayload = nil
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                guard granted, let self else { return }
                self.sessionQueue.async {
                    if !self.session.isRunning { self.session.startRunning() }
                }
            }
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            sessionQueue.async { [session] in
                if session.isRunning { session.stopRunning() }
            }
        }

        override func viewDidLayoutSubviews() {
            super.viewDidLayoutSubviews()
            previewLayer?.frame = view.bounds
        }

        private func configureSession() {
            guard let device = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: device),
                  session.canAddInput(input)
            else { return }
            session.addInput(input)

            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else { return }
            session.addOutput(output)
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]

            let layer = AVCaptureVideoPreviewLayer(session: session)
            layer.videoGravity = .resizeAspectFill
            view.layer.addSublayer(layer)
            previewLayer = layer
        }

        func metadataOutput(
            _ output: AVCaptureMetadataOutput,
            didOutput metadataObjects: [AVMetadataObject],
            from connection: AVCaptureConnection
        ) {
            guard let code = metadataObjects
                .compactMap({ $0 as? AVMetadataMachineReadableCodeObject })
                .first(where: { $0.type == .qr }),
                let payload = code.stringValue,
                payload != lastPayload
            else { return }
            lastPayload = payload
            onCode?(payload)
        }
    }
}
