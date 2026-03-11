import AppKit
import SwiftUI

struct PrinterPickerSheet: View {
    @EnvironmentObject var viewModel: ViewModel
    @Environment(\.dismiss) private var dismiss

    private var sortedProfiles: [PrinterProfile] {
        viewModel.printerProfiles.values.sorted { $0.bleIdentifier < $1.bleIdentifier }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text(L("Switch Printer"))
                    .font(.headline)
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)
            }

            if !sortedProfiles.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text(L("Saved Printers"))
                        .font(.subheadline)
                        .foregroundColor(.secondary)

                    ForEach(sortedProfiles, id: \.bleIdentifier) { profile in
                        let isCurrentConnected = profile.bleIdentifier == viewModel.printerName && viewModel.isConnected
                        let isDetectedNearby = viewModel.availablePrinters.contains(profile.bleIdentifier)
                        Button {
                            if !isCurrentConnected {
                                viewModel.switchPrinter(to: profile.bleIdentifier)
                                dismiss()
                            }
                        } label: {
                            HStack(spacing: 8) {
                                Circle()
                                    .fill(isCurrentConnected ? Color.green : (isDetectedNearby ? Color.accentColor : Color.gray.opacity(0.4)))
                                    .frame(width: 8, height: 8)

                                VStack(alignment: .leading, spacing: 2) {
                                    Text(profile.displayName)
                                        .font(.body)
                                        .foregroundColor(.primary)
                                    HStack(spacing: 6) {
                                        Text(profile.effectiveModel)
                                            .font(.caption)
                                            .foregroundColor(.secondary)
                                        if let tag = profile.filmFormatTag {
                                            Text(tag)
                                                .font(.system(size: 9, weight: .semibold))
                                                .foregroundColor(.white)
                                                .padding(.horizontal, 5)
                                                .padding(.vertical, 1)
                                                .background(Capsule().fill(.secondary))
                                        }
                                        if isDetectedNearby && !isCurrentConnected {
                                            Image(systemName: "antenna.radiowaves.left.and.right")
                                                .font(.system(size: 10, weight: .semibold))
                                                .foregroundColor(.accentColor)
                                        }
                                    }
                                }

                                Spacer()

                                if isCurrentConnected {
                                    Image(systemName: "checkmark")
                                        .font(.caption)
                                        .foregroundColor(.green)
                                }
                            }
                            .padding(.vertical, 6)
                            .padding(.horizontal, 10)
                            .background(
                                RoundedRectangle(cornerRadius: 6)
                                    .fill(Color(nsColor: .controlBackgroundColor))
                            )
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            if !viewModel.nearbyPrinters.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text(L("Nearby Printers"))
                        .font(.subheadline)
                        .foregroundColor(.secondary)

                    ForEach(viewModel.nearbyPrinters, id: \.self) { bleId in
                        Button {
                            viewModel.selectedPrinter = bleId
                            dismiss()
                            viewModel.startPairing()
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "antenna.radiowaves.left.and.right")
                                    .font(.caption)
                                    .foregroundColor(.secondary)

                                VStack(alignment: .leading, spacing: 2) {
                                    Text(bleId)
                                        .font(.body)
                                        .foregroundColor(.primary)
                                    Text(L("Tap to connect"))
                                        .font(.caption)
                                        .foregroundColor(.secondary)
                                }

                                Spacer()
                            }
                            .padding(.vertical, 6)
                            .padding(.horizontal, 10)
                            .background(
                                RoundedRectangle(cornerRadius: 6)
                                    .fill(Color(nsColor: .controlBackgroundColor))
                            )
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            VStack(spacing: 6) {
                Button {
                    viewModel.scanNearby()
                } label: {
                    HStack(spacing: 6) {
                        if viewModel.isScanning {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Image(systemName: "magnifyingglass")
                        }
                        Text(viewModel.isScanning ? L("Scanning...") : L("Scan for Printers"))
                    }
                    .frame(maxWidth: .infinity)
                }
                .controlSize(.large)
                .disabled(viewModel.isScanning)

                if !viewModel.isScanning && viewModel.nearbyPrinters.isEmpty && sortedProfiles.isEmpty {
                    Text(L("No new printers found"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
        }
        .padding(24)
        .frame(width: 340)
    }
}

struct SettingsView: View {
    @EnvironmentObject var viewModel: ViewModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text(L("Settings"))
                    .font(.headline)
                Spacer()
                Button {
                    dismiss()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, 24)
            .padding(.top, 20)
            .padding(.bottom, 8)

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    AboutSection()
                    Divider().padding(.vertical, 12)
                    LanguageAppearanceSection()
                    Divider().padding(.vertical, 12)
                    PrinterManagementSection()
                    Divider().padding(.vertical, 12)
                    ExperimentalSettingsSection()
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 24)
            }
        }
        .frame(width: 380, height: 500)
    }
}

struct AboutSection: View {
    @EnvironmentObject var viewModel: ViewModel
    @State private var isChecking = false
    @State private var checkResult: String?
    @State private var checkResultIsUpdate = false

    private var versionSummary: String {
        "\(L("App:")) v\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.0.0") | \(L("Core:")) \(viewModel.coreVersion)"
    }

    private var updateButtonTitle: String {
        if viewModel.updateAvailable != nil || checkResultIsUpdate {
            return L("Update Now")
        }
        return checkResult ?? L("Check for Updates")
    }

    var body: some View {
        VStack(spacing: 8) {
            if let icon = NSApplication.shared.applicationIconImage {
                Image(nsImage: icon)
                    .resizable()
                    .frame(width: 64, height: 64)
            }
            Text("InstantLink")
                .font(.title2)
                .fontWeight(.bold)
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(versionSummary)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 8)
                Button {
                    if viewModel.updateAvailable != nil || checkResultIsUpdate {
                        viewModel.performUpdate()
                    } else {
                        isChecking = true
                        checkResult = nil
                        Task {
                            await viewModel.checkForUpdates()
                            await MainActor.run {
                                isChecking = false
                                if viewModel.updateAvailable != nil {
                                    checkResult = nil
                                    checkResultIsUpdate = true
                                } else {
                                    checkResult = L("Up to date")
                                    checkResultIsUpdate = false
                                }
                            }
                        }
                    }
                } label: {
                    HStack(spacing: 4) {
                        if isChecking {
                            ProgressView()
                                .controlSize(.small)
                        } else if viewModel.updateAvailable != nil || checkResultIsUpdate {
                            Image(systemName: "arrow.up.circle.fill")
                        } else {
                            Image(systemName: "arrow.triangle.2.circlepath")
                        }
                        Text(updateButtonTitle)
                    }
                    .font(.caption)
                }
                .buttonStyle(.link)
                .disabled(isChecking)
            }
            .frame(maxWidth: .infinity)

            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\u{00A9} 2026 Hongjun Wu")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Spacer(minLength: 8)
                HStack(spacing: 8) {
                    Button {
                        if let url = URL(string: "https://github.com/wu-hongjun/instantlink") {
                            NSWorkspace.shared.open(url)
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "link")
                            Text(L("GitHub"))
                        }
                        .font(.caption2)
                    }
                    .buttonStyle(.link)

                    Button {
                        if let url = URL(string: "https://me.hongjunwu.com/contact/") {
                            NSWorkspace.shared.open(url)
                        }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "exclamationmark.bubble")
                            Text(L("Report an Issue"))
                        }
                        .font(.caption2)
                    }
                    .buttonStyle(.link)
                }
            }
        }
        .frame(maxWidth: .infinity)
    }
}

struct LanguageAppearanceSection: View {
    private static let supportedLanguages = [
        "en", "de", "es", "fr", "it", "ja", "ko", "pt-BR", "zh-Hans", "zh-Hant", "ar", "he"
    ]

    @EnvironmentObject var viewModel: ViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var initialLanguage: String
    @State private var selectedLanguage: String

    init() {
        let saved = Self.savedLanguageCode()
        _initialLanguage = State(initialValue: saved)
        _selectedLanguage = State(initialValue: saved)
    }

    private var languageChanged: Bool {
        selectedLanguage != initialLanguage
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L("Appearance"))
                .font(.headline)

            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(L("Language"))
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Picker("", selection: $selectedLanguage) {
                        Text(L("System Default")).tag("")
                        ForEach(Self.supportedLanguages, id: \.self) { code in
                            Text(Self.displayName(for: code)).tag(code)
                        }
                    }
                    .labelsHidden()
                    .frame(maxWidth: .infinity)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(L("Theme"))
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Picker("", selection: $viewModel.appearancePreference) {
                        Text(L("System Default")).tag(AppAppearance.system)
                        Text(L("Light")).tag(AppAppearance.light)
                        Text(L("Dark")).tag(AppAppearance.dark)
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: .infinity)
                }
            }

            if languageChanged {
                HStack {
                    Text(L("language_restart_note"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                    Spacer()
                    Button(L("Restart")) {
                        Self.persistLanguageCode(selectedLanguage)
                        initialLanguage = selectedLanguage
                        dismiss()
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
                            AppRelauncher.relaunchCurrentApp()
                        }
                    }
                    .controlSize(.small)
                }
            } else {
                Text(L("language_restart_note"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }

    private static func savedLanguageCode() -> String {
        if let langs = UserDefaults.standard.array(forKey: "AppleLanguages") as? [String],
           let first = langs.first,
           supportedLanguages.contains(first) {
            return first
        }
        return ""
    }

    private static func persistLanguageCode(_ code: String) {
        if code.isEmpty {
            UserDefaults.standard.removeObject(forKey: "AppleLanguages")
        } else {
            UserDefaults.standard.set([code], forKey: "AppleLanguages")
        }
    }

    private static func displayName(for code: String) -> String {
        let locale = Locale(identifier: code)
        return locale.localizedString(forIdentifier: code)?.localizedCapitalized ?? code
    }
}

struct PrinterManagementSection: View {
    @EnvironmentObject var viewModel: ViewModel
    @State private var editingSettingsProfile: PrinterProfile?
    @State private var deletingBleId: String?

    private var sortedProfiles: [PrinterProfile] {
        viewModel.printerProfiles.values.sorted { $0.bleIdentifier < $1.bleIdentifier }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L("Saved Printers"))
                .font(.headline)

            if sortedProfiles.isEmpty {
                Text(L("No saved printers"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.vertical, 4)
            } else {
                ForEach(sortedProfiles, id: \.bleIdentifier) { profile in
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(profile.displayName)
                                .font(.body)
                            HStack(spacing: 6) {
                                Text(profile.effectiveModel)
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                if let tag = profile.filmFormatTag {
                                    Text(tag)
                                        .font(.system(size: 9, weight: .semibold))
                                        .foregroundColor(.white)
                                        .padding(.horizontal, 5)
                                        .padding(.vertical, 1)
                                        .background(Capsule().fill(.secondary))
                                }
                            }
                        }

                        Spacer()

                        Button {
                            editingSettingsProfile = profile
                        } label: {
                            Image(systemName: "pencil")
                        }
                        .buttonStyle(.borderless)

                        Button {
                            deletingBleId = profile.bleIdentifier
                        } label: {
                            Image(systemName: "trash")
                        }
                        .buttonStyle(.borderless)
                    }
                    .padding(.vertical, 4)
                }
            }
        }
        .sheet(item: Binding<PrinterProfile?>(
            get: { editingSettingsProfile },
            set: { editingSettingsProfile = $0 }
        )) { profile in
            PrinterProfileEditorView(profile: profile, title: L("Edit Printer"))
                .environmentObject(viewModel)
        }
        .confirmationDialog(
            L("delete_printer_confirm"),
            isPresented: Binding(
                get: { deletingBleId != nil },
                set: { if !$0 { deletingBleId = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button(L("Open Bluetooth Settings")) {
                if let url = URL(string: "x-apple.systempreferences:com.apple.BluetoothSettings") {
                    NSWorkspace.shared.open(url)
                }
            }
            Button(L("Delete"), role: .destructive) {
                if let bleId = deletingBleId {
                    viewModel.deleteProfile(bleId)
                    deletingBleId = nil
                }
            }
            Button(L("Cancel"), role: .cancel) {
                deletingBleId = nil
            }
        } message: {
            Text(L("delete_printer_bluetooth_message"))
        }
    }
}

struct ExperimentalSettingsSection: View {
    @EnvironmentObject var viewModel: ViewModel
    private let ledChannels: [(label: String, color: Color)] = [
        ("R", .red),
        ("G", .green),
        ("B", .blue),
        ("W", .white),
    ]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L("Experimental Settings"))
                .font(.headline)

            Button {
                viewModel.runLedTest()
            } label: {
                HStack(spacing: 6) {
                    if viewModel.isRunningLedTest {
                        ProgressView()
                            .controlSize(.small)
                        Text(L("Running LED Test..."))
                        if let channel = viewModel.ledTestCurrentChannel {
                            Text(channel)
                                .font(.caption.monospacedDigit())
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(
                                    Capsule(style: .continuous)
                                        .fill(Color.accentColor.opacity(0.12))
                                )
                        }
                    } else {
                        Image(systemName: "lightbulb.max")
                        Text(L("Run LED Test"))
                    }
                }
            }
            .disabled(!viewModel.isConnected || viewModel.isPrinting || viewModel.isRunningLedTest)

            HStack(spacing: 8) {
                ForEach(ledChannels, id: \.label) { channel in
                    LedTestChannelChip(
                        label: channel.label,
                        color: channel.color,
                        isActive: viewModel.ledTestCurrentChannel == channel.label
                    )
                }
            }

            if !viewModel.isConnected {
                Text(L("Connect to your printer"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }
}

private struct LedTestChannelChip: View {
    let label: String
    let color: Color
    let isActive: Bool

    var body: some View {
        Text(label)
            .font(.caption.weight(.semibold))
            .foregroundStyle(label == "W" ? Color.primary : .white)
            .frame(width: 24, height: 24)
            .background(
                Circle()
                    .fill(color.opacity(label == "W" ? 0.95 : 0.9))
            )
            .overlay(
                Circle()
                    .stroke(isActive ? Color.accentColor : Color.primary.opacity(label == "W" ? 0.10 : 0), lineWidth: isActive ? 2 : 0)
            )
            .scaleEffect(isActive ? 1.08 : 1.0)
            .animation(.snappy(duration: 0.18), value: isActive)
    }
}
