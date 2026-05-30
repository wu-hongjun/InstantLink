import SwiftUI

/// Passive banner shown in the Print main view when a Bridge is connected.
/// Stays silent when the Bridge is working (paired + present) and surfaces a
/// quiet CTA only when the user must act (unpaired) or briefly hints when the
/// Bridge has just dropped off.
struct BridgeDiscoveryBanner: View {
    let snapshot: BridgeControlSnapshot
    let onOpen: () -> Void

    var body: some View {
        Group {
            switch snapshot.discovery {
            case .searching:
                EmptyView()
            case .found:
                if case .paired = snapshot.pairing {
                    // Bridge is working. Nothing for the user to do — stay quiet.
                    EmptyView()
                } else {
                    setupStrip
                }
            case .lost:
                disconnectedStrip
            }
        }
    }

    // MARK: - Strips

    private var setupStrip: some View {
        HStack(spacing: 8) {
            Image(systemName: "link.badge.plus")
                .font(.caption)
                .foregroundColor(.accentColor)
            Text(L("InstantLink Bridge ready to set up"))
                .font(.caption)
                .lineLimit(1)
            Spacer(minLength: 4)
            Button(L("Set up")) {
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
    }

    private var disconnectedStrip: some View {
        HStack(spacing: 8) {
            Image(systemName: "antenna.radiowaves.left.and.right.slash")
                .font(.caption)
                .foregroundColor(.secondary)
            Text(L("Bridge disconnected"))
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
