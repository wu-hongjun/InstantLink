import SwiftUI

/// Single shared component for top-of-MainView banner strips. Replaces the
/// three independent banner systems (BridgeDiscoveryBanner, update banners,
/// status banner) so the Main window shows at most one banner at a time, with
/// precedence resolved at the call site in `MainView`.
struct BannerStrip: View {
    enum Tone {
        case info, success, warning, error, accent
    }

    struct Action {
        let label: String
        let onTap: () -> Void
        var prominent: Bool = false
    }

    let tone: Tone
    let icon: String
    let text: String
    var progress: Double? = nil
    var primary: Action? = nil
    var dismiss: Action? = nil

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.caption)
                .foregroundColor(iconColor)
            Text(text)
                .font(.caption)
                .lineLimit(2)
            Spacer(minLength: 4)
            if let progress {
                ProgressView(value: progress)
                    .tint(.brandAccent)
                    .frame(width: 60)
                Text("\(Int(progress * 100))%")
                    .font(.caption)
                    .monospacedDigit()
            }
            if let primary {
                if primary.prominent {
                    SwiftUI.Button(primary.label, action: primary.onTap)
                        .font(.caption)
                        .buttonStyle(.borderedProminent)
                        .tint(.brandAccent)
                        .controlSize(.small)
                } else {
                    SwiftUI.Button(primary.label, action: primary.onTap)
                        .font(.caption)
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
            }
            if let dismiss {
                SwiftUI.Button(dismiss.label, action: dismiss.onTap)
                    .font(.caption)
                    .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(background)
        .transition(.move(edge: .top).combined(with: .opacity))
    }

    private var iconColor: Color {
        switch tone {
        case .info: return .blue
        case .success: return .green
        case .warning: return .orange
        case .error: return .red
        case .accent: return .brandAccent
        }
    }

    private var background: Color {
        switch tone {
        case .info: return Color.blue.opacity(0.10)
        case .success: return Color.green.opacity(0.12)
        case .warning: return Color.orange.opacity(0.14)
        case .error: return Color.red.opacity(0.14)
        case .accent: return Color.brandAccent.opacity(0.10)
        }
    }
}
