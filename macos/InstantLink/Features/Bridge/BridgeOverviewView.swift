import SwiftUI

struct BridgeOverviewView: View {
    @ObservedObject var coordinator: BridgeControlCoordinator
    @State private var showPairingSheet = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                switch coordinator.snapshot.discovery {
                case .searching:
                    searchingCard
                case .lost(let device, _):
                    disconnectedCard(device: device)
                case .found(let device):
                    deviceCard(device: device)
                }

                if isUnpaired {
                    pairCTACard
                }

                if let status = coordinator.snapshot.status {
                    networkCard(status: status)
                    printerCard(printer: status.printer)
                    uploadsCard(status: status)
                }

                if let error = coordinator.snapshot.lastError {
                    errorCard(error: error)
                }

                Spacer(minLength: 8)
            }
            .padding(16)
        }
        .sheet(isPresented: $showPairingSheet) {
            BridgePairingView(coordinator: coordinator, isPresented: $showPairingSheet)
        }
    }

    // MARK: - State helpers

    private var isUnpaired: Bool {
        switch coordinator.snapshot.pairing {
        case .paired: return false
        default: return true
        }
    }

    // MARK: - Cards

    private var searchingCard: some View {
        BridgeCard(title: L("bridge_overview_searching_title")) {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text(L("bridge_overview_searching_message"))
                    .font(.callout)
                    .foregroundColor(.secondary)
            }
        }
    }

    private func disconnectedCard(device: BridgeDevice?) -> some View {
        BridgeCard(title: L("bridge_overview_disconnected_title")) {
            VStack(alignment: .leading, spacing: 6) {
                if let device {
                    Text(device.deviceID)
                        .font(.callout.weight(.semibold))
                }
                Text(L("bridge_overview_disconnected_message"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    private func deviceCard(device: BridgeDevice) -> some View {
        BridgeCard(title: L("bridge_overview_device_title")) {
            VStack(alignment: .leading, spacing: 6) {
                infoRow(label: L("bridge_overview_field_device_id"), value: device.deviceID)
                infoRow(label: L("bridge_overview_field_name"), value: device.displayName)
                infoRow(label: L("bridge_overview_field_version"), value: "v\(device.softwareVersion)")
                infoRow(label: L("bridge_overview_field_api"), value: device.apiVersion)
                if let endpoint = device.endpointURL {
                    infoRow(label: L("bridge_overview_field_endpoint"), value: endpoint.absoluteString)
                }
            }
        }
    }

    private var pairCTACard: some View {
        BridgeCard(title: L("bridge_overview_pair_title")) {
            VStack(alignment: .leading, spacing: 8) {
                Text(L("bridge_overview_pair_message"))
                    .font(.callout)
                    .foregroundColor(.secondary)
                Button(L("bridge_overview_pair_button")) {
                    showPairingSheet = true
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.regular)
            }
        }
    }

    private func networkCard(status: BridgeStatus) -> some View {
        BridgeCard(title: L("bridge_overview_network_title")) {
            VStack(alignment: .leading, spacing: 6) {
                if let network = status.network {
                    infoRow(label: L("bridge_overview_network_mode"), value: network.label)
                    if let address = network.address {
                        infoRow(label: L("bridge_overview_network_address"), value: address)
                    }
                    infoRow(
                        label: L("bridge_overview_network_status"),
                        value: network.connected ? L("connected") : L("disconnected")
                    )
                } else {
                    Text(L("bridge_overview_network_unknown"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                infoRow(
                    label: L("bridge_overview_network_upload_mode"),
                    value: uploadModeLabel(status.activeUploadMode)
                )
            }
        }
    }

    private func printerCard(printer: BridgePrinterStatus?) -> some View {
        BridgeCard(title: L("bridge_overview_printer_title")) {
            if let printer {
                VStack(alignment: .leading, spacing: 6) {
                    infoRow(
                        label: L("bridge_overview_printer_name"),
                        value: printer.displayName ?? L("bridge_overview_printer_unknown")
                    )
                    if let model = printer.model {
                        infoRow(label: L("bridge_overview_printer_model"), value: model)
                    }
                    if let film = printer.filmRemaining {
                        infoRow(label: L("bridge_overview_printer_film"), value: "\(film)")
                    }
                    if let battery = printer.batteryPercent {
                        infoRow(label: L("bridge_overview_printer_battery"), value: "\(battery)%")
                    }
                    infoRow(
                        label: L("bridge_overview_printer_status"),
                        value: printer.connected ? L("connected") : L("disconnected")
                    )
                }
            } else {
                Text(L("bridge_overview_printer_none"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    private func uploadsCard(status: BridgeStatus) -> some View {
        BridgeCard(title: L("bridge_overview_uploads_title")) {
            if let last = status.lastUpload {
                VStack(alignment: .leading, spacing: 4) {
                    Text(last.filename ?? L("bridge_overview_uploads_unknown_file"))
                        .font(.callout)
                    Text(last.status)
                        .font(.caption)
                        .foregroundColor(.secondary)
                    if let received = last.receivedAt {
                        Text("\(L("bridge_overview_uploads_received")) \(received)")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }
            } else {
                Text(L("bridge_overview_uploads_none"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    private func errorCard(error: BridgeErrorPayload) -> some View {
        BridgeCard(title: L("bridge_overview_error_title")) {
            Text(error.message)
                .font(.caption)
                .foregroundColor(.red)
        }
    }

    private func infoRow(label: String, value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
                .frame(width: 110, alignment: .leading)
            Text(value)
                .font(.callout)
                .textSelection(.enabled)
                .lineLimit(2)
            Spacer()
        }
    }

    private func uploadModeLabel(_ mode: BridgeUploadMode) -> String {
        switch mode {
        case .bridgeWiFi: return L("bridge_upload_mode_bridge_wifi")
        case .sameWiFi: return L("bridge_upload_mode_same_wifi")
        case .usbDebug: return L("bridge_upload_mode_usb_debug")
        case .disabled: return L("bridge_upload_mode_disabled")
        case .unknown: return L("bridge_upload_mode_unknown")
        }
    }
}

/// Small styled card used by the overview tab.
struct BridgeCard<Content: View>: View {
    let title: String
    let content: () -> Content

    init(title: String, @ViewBuilder content: @escaping () -> Content) {
        self.title = title
        self.content = content
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            content()
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.secondary.opacity(0.08))
        )
    }
}
