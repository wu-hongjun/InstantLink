import SwiftUI

/// Pairing details plus the two escape hatches: re-pair (scan a new QR,
/// overwriting the stored pairing) and forget (drop token, network config,
/// and sync history).
struct SettingsView: View {
    @EnvironmentObject private var model: SyncViewModel
    @State private var isRepairPresented = false
    @State private var isForgetConfirmPresented = false

    var body: some View {
        Form {
            if let pairing = model.pairing {
                Section("Bridge") {
                    LabeledContent("Device", value: pairing.deviceID)
                    LabeledContent("Address", value: "\(pairing.host):\(pairing.port)")
                    if let ssid = pairing.ssid {
                        LabeledContent("Network", value: ssid)
                    }
                    if let proto = model.bridgeStatus?.proto {
                        LabeledContent("Sync protocol", value: "v\(proto)")
                    }
                }
            }

            Section("Sync") {
                LabeledContent("Photos synced", value: "\(model.syncedCount)")
            }

            Section {
                Button("Re-pair with Bridge") {
                    isRepairPresented = true
                }
                Button("Forget this Bridge", role: .destructive) {
                    isForgetConfirmPresented = true
                }
            } footer: {
                Text("Forgetting removes the pairing token, the saved Wi-Fi configuration, and the sync history. Photos already in your library are not affected.")
            }
        }
        .navigationTitle("Settings")
        .sheet(isPresented: $isRepairPresented) {
            OnboardingView()
        }
        .confirmationDialog(
            "Forget this Bridge?",
            isPresented: $isForgetConfirmPresented,
            titleVisibility: .visible
        ) {
            Button("Forget", role: .destructive) {
                model.forgetBridge()
            }
        } message: {
            Text("You will need to scan the pairing QR code again to reconnect.")
        }
    }
}
