import SwiftUI

/// Photos-style collapsible section header — plan 049 redesign.
///
/// Single horizontal row: chevron toggle, section icon, title, optional
/// `Reset` link (only when non-neutral), optional `AUTO` badge button, and
/// optional on/off circle toggle. Sections are intended to default
/// collapsed; only Light, Color, and Black & White ship expanded by default.
struct AdjustmentSectionHeader: View {
    @Binding var isExpanded: Bool
    let title: LocalizedStringKey

    /// SF Symbol name. Each section picks the closest Photos match
    /// (see plan 049 §icons for the canonical list).
    var systemImage: String = "circle"

    /// Optional Auto handler; when present an `AUTO` pill badge is shown.
    var onAuto: (() -> Void)? = nil

    /// Optional Reset handler; when present and `isNeutral == false` the
    /// curved-arrow reset glyph is shown.
    var onReset: (() -> Void)? = nil

    /// `true` when the section state matches its neutral baseline. Hides
    /// the Reset glyph when neutral; ignored if `onReset == nil`.
    var isNeutral: Bool = true

    /// Optional on-off toggle. When provided the trailing circle glyph
    /// reads the binding; clicking flips it.
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

            Image(systemName: systemImage)
                .font(.callout)
                .foregroundStyle(.secondary)
                .frame(width: 18, alignment: .center)

            Text(title)
                .font(.callout.weight(.semibold))
                .foregroundStyle(.primary)

            Spacer()

            if let onReset, !isNeutral {
                Button {
                    onReset()
                } label: {
                    Image(systemName: "arrow.uturn.backward")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .help(L("adjust_reset"))
            }

            if let onAuto {
                Button {
                    onAuto()
                } label: {
                    Text(L_key("adjust_auto"))
                        .font(.caption2.weight(.bold))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(
                            Capsule()
                                .fill(Color.primary.opacity(0.08))
                        )
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
            }

            if let enabledBinding {
                Button {
                    enabledBinding.wrappedValue.toggle()
                } label: {
                    Image(systemName: enabledBinding.wrappedValue
                        ? "circle.inset.filled"
                        : "circle")
                        .font(.callout)
                        .foregroundStyle(enabledBinding.wrappedValue
                            ? Color.accentColor
                            : .secondary)
                }
                .buttonStyle(.plain)
            }
        }
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.isHeader)
    }
}
