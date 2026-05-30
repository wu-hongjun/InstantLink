import SwiftUI

/// Passive banner shown in the Print main view when a Bridge is connected
/// via USB. Silent when nothing is found, and fades to a disconnected state
/// when discovery loses the device.
struct BridgeDiscoveryBanner: View {
    let snapshot: BridgeControlSnapshot
    let onOpen: () -> Void

    var body: some View {
        Group {
            switch snapshot.discovery {
            case .searching:
                EmptyView()
            case .found(let device):
                HStack(spacing: 8) {
                    Image(systemName: "antenna.radiowaves.left.and.right")
                        .font(.caption)
                        .foregroundColor(.accentColor)
                    Text(label(for: device))
                        .font(.caption)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                    Button(L("bridge_banner_open_control")) {
                        onOpen()
                    }
                    .font(.caption)
                    .buttonStyle(.borderless)
                    .controlSize(.small)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.accentColor.opacity(0.10))
                .transition(.move(edge: .top).combined(with: .opacity))
            case .lost(let device, _):
                HStack(spacing: 8) {
                    Image(systemName: "antenna.radiowaves.left.and.right.slash")
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Text(lostLabel(for: device))
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                    Spacer(minLength: 4)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.secondary.opacity(0.08))
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
    }

    private func label(for device: BridgeDevice) -> String {
        let version = device.softwareVersion.isEmpty ? "" : " — v\(device.softwareVersion)"
        return "Bridge \(device.deviceID)\(version) — \(L("connected_via_usb"))"
    }

    private func lostLabel(for device: BridgeDevice?) -> String {
        if let device {
            return "Bridge \(device.deviceID) — \(L("disconnected"))"
        }
        return L("bridge_disconnected")
    }
}
