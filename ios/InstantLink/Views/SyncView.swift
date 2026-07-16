import SwiftUI

/// Main screen once paired: Bridge status card, live transfer list, synced
/// count, and a manual "Sync now" trigger. Auto-sync runs whenever the app is
/// foregrounded; this view just renders its state.
struct SyncView: View {
    @EnvironmentObject private var model: SyncViewModel

    var body: some View {
        List {
            Section {
                bridgeStatusCard
            }

            if let error = model.lastError {
                Section {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .font(.subheadline)
                }
            }

            if model.transfers.isEmpty {
                Section {
                    emptyTransfers
                }
            } else {
                Section("Transfers") {
                    ForEach(model.transfers) { transfer in
                        TransferRow(transfer: transfer)
                    }
                }
            }
        }
        .navigationTitle("InstantLink")
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                NavigationLink {
                    SettingsView()
                } label: {
                    Image(systemName: "gearshape")
                }
            }
        }
        .safeAreaInset(edge: .bottom) {
            syncNowButton
        }
        .refreshable {
            await model.syncOnce()
        }
    }

    // MARK: - Status card

    private var bridgeStatusCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "dot.radiowaves.left.and.right")
                    .font(.title2)
                    .foregroundStyle(model.isBridgeReachable ? .green : .secondary)
                VStack(alignment: .leading) {
                    Text(model.pairing?.deviceID ?? "Bridge")
                        .font(.headline)
                    Text(model.isBridgeReachable ? "Connected" : "Looking for Bridge…")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if model.isSyncing {
                    ProgressView()
                }
            }

            Divider()

            HStack {
                statPill(
                    value: model.bridgeStatus.map { "\($0.outboxDepth)" } ?? "—",
                    label: "waiting to sync"
                )
                Spacer()
                statPill(value: "\(model.syncedCount)", label: "synced")
            }
        }
        .padding(.vertical, 4)
    }

    // MARK: - Empty transfers

    private var emptyTransfers: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("No photos yet")
                .font(.subheadline.weight(.semibold))
            Text("Photos your Bridge receives will appear here while the app is open.")
                .font(.footnote)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 6)
    }

    private func statPill(value: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.title3.monospacedDigit().bold())
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    // MARK: - Sync now

    private var syncNowButton: some View {
        Button {
            model.syncNow()
        } label: {
            Label(
                model.isSyncing ? "Syncing…" : "Sync now",
                systemImage: "arrow.triangle.2.circlepath"
            )
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
        .disabled(model.isSyncing)
        .padding()
        .background(.bar)
    }
}

// MARK: - Transfer row

private struct TransferRow: View {
    let transfer: SyncViewModel.Transfer

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text(transfer.fileName)
                    .font(.subheadline)
                    .lineLimit(1)
                Spacer()
                stateBadge
            }
            if transfer.state == .downloading {
                ProgressView(value: transfer.fractionComplete)
                Text(
                    "\(transfer.bytesReceived.formatted(.byteCount(style: .file))) of \(transfer.sizeBytes.formatted(.byteCount(style: .file)))"
                )
                .font(.caption)
                .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 2)
    }

    @ViewBuilder
    private var stateBadge: some View {
        switch transfer.state {
        case .waiting:
            Image(systemName: "clock")
                .foregroundStyle(.secondary)
        case .downloading:
            Image(systemName: "arrow.down.circle")
                .foregroundStyle(Color.brandAccent)
        case .saving:
            ProgressView()
                .controlSize(.small)
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .failed(let message):
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.red)
                .accessibilityLabel(message)
        }
    }
}
