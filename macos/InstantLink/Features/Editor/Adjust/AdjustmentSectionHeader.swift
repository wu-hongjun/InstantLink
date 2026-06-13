import SwiftUI

/// Photos-style collapsible section header.
///
/// Visually a compact row: chevron toggle, title, optional `Auto` /
/// `Reset` buttons, optional on-off `Toggle`. Reused by every adjustment
/// panel that follows.
struct AdjustmentSectionHeader: View {
    @Binding var isExpanded: Bool
    let title: LocalizedStringKey

    /// Optional Auto handler; when present the Auto button is shown.
    var onAuto: (() -> Void)? = nil

    /// Optional Reset handler; when present and `isNeutral == false` the
    /// Reset button is shown.
    var onReset: (() -> Void)? = nil

    /// `true` when the section state matches its neutral baseline. Hides
    /// the Reset button when neutral; ignored if `onReset == nil`.
    var isNeutral: Bool = true

    /// Optional on-off toggle (used by B&W in PR #13). When provided the
    /// switch shows on the trailing edge.
    var enabledBinding: Binding<Bool>? = nil

    var body: some View {
        HStack(spacing: 6) {
            Button {
                withAnimation(.easeInOut(duration: 0.15)) {
                    isExpanded.toggle()
                }
            } label: {
                Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 12, alignment: .center)
            }
            .buttonStyle(.plain)

            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundStyle(.primary)

            Spacer()

            if let onAuto {
                Button(L("adjust_auto")) { onAuto() }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
            }

            if let onReset, !isNeutral {
                Button(L("adjust_reset")) { onReset() }
                    .buttonStyle(.borderless)
                    .controlSize(.small)
            }

            if let enabledBinding {
                Toggle("", isOn: enabledBinding)
                    .toggleStyle(.switch)
                    .controlSize(.small)
                    .labelsHidden()
            }
        }
        .contentShape(Rectangle())
    }
}
