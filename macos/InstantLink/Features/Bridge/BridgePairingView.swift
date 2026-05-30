import AppKit
import SwiftUI

/// Wizard view: explains how to open the pairing window on the Bridge LCD,
/// accepts the 6-digit code, then forwards it to the coordinator.
struct BridgePairingView: View {
    @ObservedObject var coordinator: BridgeControlCoordinator
    @Binding var isPresented: Bool

    @State private var code: String = ""
    @State private var displayName: String = Host.current().localizedName ?? "Mac"
    @State private var submitting: Bool = false
    @State private var localError: String?
    @State private var nowTick: Date = Date()

    private let codeLength = 6
    private let countdownTimer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header

            Divider()

            content

            Divider()

            footer
        }
        .padding(20)
        .frame(minWidth: 460, minHeight: 360)
        .onReceive(countdownTimer) { tick in
            nowTick = tick
        }
    }

    // MARK: - Sections

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(L("Pair Bridge"))
                .font(.title2.weight(.semibold))
            Spacer()
            Button(L("Cancel")) {
                isPresented = false
            }
            .keyboardShortcut(.cancelAction)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch coordinator.snapshot.pairing {
        case .unpaired:
            instructionsStep
        case .pairingWindowOpen, .awaitingCode:
            codeEntryStep
        case .completing:
            completingStep
        case .paired:
            succeededStep
        case .failed(let reason):
            failureStep(reason: reason)
        }
    }

    private var instructionsStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            stepHeader(number: 1, title: L("Open the pairing window on the Bridge"))
            Text(L("On the Bridge LCD, open Settings → Network → Authorize Mac. Hold KEY3 for one second to start."))
                .font(.callout)
                .foregroundColor(.secondary)
            HStack(spacing: 8) {
                ProgressView().controlSize(.small)
                Text(L("Waiting for the Bridge to open its pairing window…"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    private var codeEntryStep: some View {
        VStack(alignment: .leading, spacing: 10) {
            stepHeader(number: 2, title: L("Enter the 6-digit code"))
            Text(L("Enter the 6-digit code shown on the Bridge."))
                .font(.callout)
                .foregroundColor(.secondary)

            TextField(L("000000"), text: $code)
                .textFieldStyle(.roundedBorder)
                .font(.system(size: 22, weight: .semibold, design: .monospaced))
                .frame(maxWidth: 220)
                .onChange(of: code) { _, new in
                    code = Self.sanitize(code: new, max: codeLength)
                }
                .disableAutocorrection(true)

            VStack(alignment: .leading, spacing: 4) {
                Text(L("This Mac's name"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                TextField(L("Mac"), text: $displayName)
                    .textFieldStyle(.roundedBorder)
                    .frame(maxWidth: 320)
            }

            if let countdown = countdownString() {
                Text(countdown)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            if let localError {
                Text(localError)
                    .font(.caption)
                    .foregroundColor(.red)
            }
        }
        .onAppear {
            coordinator.acknowledgePairingWindowOpen()
        }
    }

    private var completingStep: some View {
        HStack(spacing: 10) {
            ProgressView().controlSize(.small)
            Text(L("Submitting…"))
                .font(.callout)
        }
    }

    private var succeededStep: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "checkmark.seal.fill")
                    .foregroundColor(.green)
                Text(L("Bridge paired"))
                    .font(.title3.weight(.semibold))
            }
            Text(L("Pairing complete. You can now manage this Bridge from here."))
                .font(.callout)
                .foregroundColor(.secondary)
        }
    }

    private func failureStep(reason: BridgePairingFailureReason) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: "xmark.octagon.fill")
                    .foregroundColor(.red)
                Text(L("Pairing failed"))
                    .font(.title3.weight(.semibold))
            }
            Text(reason.localizedMessage)
                .font(.callout)
                .foregroundColor(.secondary)
        }
    }

    @ViewBuilder
    private var footer: some View {
        HStack {
            Spacer()
            switch coordinator.snapshot.pairing {
            case .pairingWindowOpen, .awaitingCode:
                Button(L("Pair")) {
                    Task { await submit() }
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(submitting || code.count != codeLength)
            case .paired:
                Button(L("Done")) {
                    isPresented = false
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
            case .failed:
                Button(L("Try Again")) {
                    localError = nil
                    coordinator.acknowledgePairingWindowOpen()
                }
                Button(L("Close")) {
                    isPresented = false
                }
            case .completing:
                ProgressView().controlSize(.small)
            case .unpaired:
                EmptyView()
            }
        }
    }

    // MARK: - Helpers

    private func stepHeader(number: Int, title: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: "\(number).circle.fill")
                .foregroundColor(.accentColor)
            Text(title)
                .font(.headline)
        }
    }

    private func countdownString() -> String? {
        let expiresAt: Date?
        switch coordinator.snapshot.pairing {
        case .pairingWindowOpen(let date), .awaitingCode(let date):
            expiresAt = date
        default:
            expiresAt = nil
        }
        guard let expiresAt else { return nil }
        let remaining = Int(expiresAt.timeIntervalSince(nowTick))
        if remaining <= 0 {
            return L("Pairing window expired")
        }
        return "\(L("Time remaining")): \(remaining)s"
    }

    private func submit() async {
        guard !submitting else { return }
        guard Self.validate(code: code, expected: codeLength) else {
            localError = L("Enter the 6-digit code from the Bridge.")
            return
        }
        submitting = true
        localError = nil
        let ok = await coordinator.pair(code: code, displayName: displayName)
        submitting = false
        if ok {
            // The footer button switches to Done once `.paired` propagates.
        }
    }

    static func sanitize(code: String, max: Int) -> String {
        let digits = code.filter { $0.isNumber }
        return String(digits.prefix(max))
    }

    static func validate(code: String, expected: Int) -> Bool {
        code.count == expected && code.allSatisfy { $0.isNumber }
    }
}
