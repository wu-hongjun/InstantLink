import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// Backup tab content. As of plan 038 polish (v0.1.25) the bridge does not yet
/// expose byte-level transport for backup/restore archives, so the Mac surface
/// is a clear "coming soon" affordance: the cards stay visible, but the action
/// buttons are disabled with help-text explaining the missing bridge support.
/// When the bridge ships file-transfer endpoints the cards activate
/// automatically (no UI restructuring needed). The view keeps the operation
/// progress + last-result cards rendered so any in-flight coordinator state
/// (e.g. a previous build that wired the round-trip) still surfaces.
struct BridgeBackupView: View {
    @ObservedObject var coordinator: BridgeControlCoordinator
    @ObservedObject var backupCoordinator: BridgeBackupCoordinator
    @ObservedObject var diagnosticsCoordinator: BridgeDiagnosticsCoordinator

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                if isUnpaired {
                    if isRecoveryOwningMessage {
                        // Recovery banner already explains why management
                        // routes are unreachable; suppress the pairing card.
                        EmptyView()
                    } else {
                        pairingRequiredCard
                    }
                } else {
                    backupCard
                    restoreCard
                    if let result = backupCoordinator.snapshot.lastResult {
                        resultCard(result: result)
                    }
                    if backupCoordinator.snapshot.operation != nil {
                        operationCard
                    }
                }
                Spacer(minLength: 8)
            }
            .padding(16)
        }
    }

    // MARK: - Pairing gate

    private var isUnpaired: Bool {
        if case .paired = coordinator.snapshot.pairing { return false }
        return true
    }

    /// True when the recovery banner is showing a state where management
    /// routes are unreachable. In that case the pairing card would
    /// contradict the banner, so the tab body should defer to the banner.
    private var isRecoveryOwningMessage: Bool {
        switch diagnosticsCoordinator.snapshot.recovery {
        case .managementUnavailable, .restartInFlight, .unrecoverable:
            return true
        case .ok, .checking, .recovered:
            return false
        }
    }

    private var pairingRequiredCard: some View {
        BridgeCard(title: L("Backup")) {
            Text(L("Pair this Mac with the Bridge to back up or restore."))
                .font(.callout)
                .foregroundColor(.secondary)
        }
    }

    // MARK: - Back up card

    private var backupCard: some View {
        BridgeCard(title: L("Back up Bridge")) {
            VStack(alignment: .leading, spacing: 10) {
                Text(L("Save a Bridge backup file you can restore later. Bridge file-transfer endpoints are coming in a future release; the backup tab will activate automatically when the connected Bridge supports it."))
                    .font(.callout)
                    .foregroundColor(.secondary)
                Button {
                    // Disabled until bridge ships file-transfer endpoints.
                } label: {
                    Text(L("Back up Bridge…"))
                }
                .buttonStyle(.borderedProminent)
                .disabled(true)
                .help(L("Coming soon — bridge file-transfer endpoints are not yet available."))
            }
        }
    }

    // MARK: - Restore card

    private var restoreCard: some View {
        BridgeCard(title: L("Restore from file")) {
            VStack(alignment: .leading, spacing: 10) {
                Text(L("Restore a previously-saved Bridge backup. This will activate automatically when the connected Bridge supports backup file transfer."))
                    .font(.callout)
                    .foregroundColor(.secondary)
                Button {
                    // Disabled until bridge ships file-transfer endpoints.
                } label: {
                    Text(L("Restore from file…"))
                }
                .disabled(true)
                .help(L("Coming soon — bridge file-transfer endpoints are not yet available."))
            }
        }
    }

    // MARK: - Operation card

    private var operationCard: some View {
        BridgeCard(title: L("In progress")) {
            HStack(spacing: 10) {
                ProgressView().controlSize(.small)
                Text(operationLabel)
                    .font(.callout)
                Spacer()
            }
        }
    }

    private var operationLabel: String {
        switch backupCoordinator.snapshot.operation {
        case .creatingBackup:
            return L("Creating backup…")
        case .downloadingBackup:
            return L("Downloading backup…")
        case .restoringBackup(let phase):
            switch phase {
            case .uploading: return L("Uploading backup…")
            case .applying: return L("Applying backup…")
            case .restarting: return L("Restarting Bridge…")
            case .verifying: return L("Verifying Bridge…")
            }
        case .none:
            return L("Working…")
        }
    }

    // MARK: - Result card

    @ViewBuilder
    private func resultCard(result: BridgeBackupSnapshot.Result) -> some View {
        BridgeCard(title: L("Last result")) {
            VStack(alignment: .leading, spacing: 10) {
                switch result {
                case .backupCreated(let path, _, _):
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L("Backup saved."))
                                .font(.callout.weight(.semibold))
                            Text(path.lastPathComponent)
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .textSelection(.enabled)
                        }
                        Spacer()
                    }
                    HStack(spacing: 8) {
                        Button(L("Show in Finder")) {
                            NSWorkspace.shared.activateFileViewerSelecting([path])
                        }
                        Button(L("Dismiss")) {
                            backupCoordinator.clearLastResult()
                        }
                    }
                case .backupRestored:
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                        Text(L("Bridge restored. Reconnecting…"))
                            .font(.callout)
                        Spacer()
                    }
                    Button(L("Dismiss")) {
                        backupCoordinator.clearLastResult()
                    }
                case .failed(let reason, _):
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "exclamationmark.octagon.fill")
                            .foregroundColor(.red)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(L("Backup failed"))
                                .font(.callout.weight(.semibold))
                                .foregroundColor(.red)
                            Text(reason)
                                .font(.caption)
                                .foregroundColor(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                    }
                    Button(L("Dismiss")) {
                        backupCoordinator.clearLastResult()
                    }
                }
            }
        }
    }
}
