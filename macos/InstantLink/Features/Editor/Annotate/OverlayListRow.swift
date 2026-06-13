import SwiftUI

/// Single row in the Annotate tab's overlay list. Shows an icon, the overlay's
/// effective title, and inline hide / lock / delete affordances. Ported from
/// the retired legacy editor (plan 048 PR #14).
struct OverlayListRow: View {
    @ObservedObject var state: EditorViewState
    let overlay: OverlayItem
    @State private var isHovered = false

    var body: some View {
        HStack(spacing: 8) {
            Button {
                if isSelected {
                    state.selectOverlay(nil)
                } else {
                    state.selectOverlay(overlay.id)
                }
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: symbolName)
                        .frame(width: 16)
                        .foregroundColor(isSelected ? .accentColor : .secondary)

                    Text(overlay.displayTitle)
                        .font(.callout)
                        .lineLimit(1)
                        .foregroundColor(.primary)

                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Button {
                state.updateOverlay(id: overlay.id) { $0.isLocked.toggle() }
            } label: {
                Image(systemName: overlay.isLocked ? "lock.fill" : "lock.open")
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
            .opacity(actionOpacity)
            // Help text describes the ACTION the button performs, which is the
            // opposite of the current state (PR #14 audit L1 fix).
            .help(L(overlay.isLocked ? "annotate_overlay_unlock" : "annotate_overlay_lock"))

            Button {
                state.updateOverlay(id: overlay.id) { $0.isHidden.toggle() }
            } label: {
                Image(systemName: overlay.isHidden ? "eye.slash" : "eye")
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
            .opacity(actionOpacity)
            .help(L(overlay.isHidden ? "annotate_overlay_show" : "annotate_overlay_hide"))

            Button {
                state.deleteOverlay(id: overlay.id)
            } label: {
                Image(systemName: "trash")
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
            .opacity(actionOpacity)
            .help(L("Delete"))
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(
                    isSelected
                        ? Color.accentColor.opacity(0.14)
                        : (isHovered ? Color.white.opacity(0.07) : Color.white.opacity(0.03))
                )
        )
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(
                    isSelected ? Color.accentColor.opacity(0.34) : Color.white.opacity(isHovered ? 0.16 : 0.06),
                    lineWidth: 1
                )
        )
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .onHover { hovered in
            withAnimation(.easeOut(duration: 0.15)) {
                isHovered = hovered
            }
        }
    }

    private var isSelected: Bool { state.selectedOverlayID == overlay.id }

    private var actionOpacity: Double { (isHovered || isSelected) ? 1 : 0.55 }

    private var symbolName: String {
        switch overlay.kind {
        case .text: return "textformat"
        case .qrCode: return "qrcode"
        case .timestamp: return "calendar"
        case .image: return "photo"
        case .location: return "mappin.and.ellipse"
        }
    }
}
