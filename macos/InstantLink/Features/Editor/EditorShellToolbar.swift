import SwiftUI

/// Plan 049: Photos.app-style top bar.
///
/// Left third: a zoom slider with `-` and `+` end-caps (range `-1…+1`,
/// neutral 0). Center third: a pill-shaped segmented control with the four
/// editor tabs (Adjust / Filters / Crop / Annotate). Right third: a row of
/// icon-only action buttons (info / more / favorite / rotate / wand
/// auto-enhance) followed by a yellow Done capsule.
///
/// The undo / redo / revert controls that used to live here in v0.1.45 are
/// folded into the More (`ellipsis.circle`) menu so the top bar matches the
/// Photos layout density.
struct EditorShellTopBar: View {
    @ObservedObject var state: EditorViewState
    let onDone: () -> Void
    let onRevert: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            zoomCluster
            Spacer(minLength: 12)
            EditorPillTabs(active: $state.activeTab)
            Spacer(minLength: 12)
            actionCluster
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 6)
    }

    // MARK: - Zoom slider (left third)

    private var zoomCluster: some View {
        HStack(spacing: 6) {
            Button {
                state.zoomLevel = max(-1, state.zoomLevel - 0.1)
            } label: {
                Image(systemName: "minus")
                    .font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderless)
            .help(L("editor_zoom"))

            Slider(value: $state.zoomLevel, in: -1...1)
                .frame(width: 120)
                .controlSize(.small)
                .help(L("editor_zoom"))

            Button {
                state.zoomLevel = min(1, state.zoomLevel + 0.1)
            } label: {
                Image(systemName: "plus")
                    .font(.caption.weight(.semibold))
            }
            .buttonStyle(.borderless)
            .help(L("editor_zoom"))
        }
    }

    // MARK: - Right action cluster

    private var actionCluster: some View {
        HStack(spacing: 4) {
            Button { /* Info — placeholder per Photos parity. */ } label: {
                Image(systemName: "info.circle")
            }
            .buttonStyle(.borderless)
            .help(L("editor_info"))

            Menu {
                Button(L("editor_undo")) { state.undo() }
                    .disabled(!state.history.canUndo)
                Button(L("editor_redo")) { state.redo() }
                    .disabled(!state.history.canRedo)
                Divider()
                Button(L("editor_revert")) { onRevert() }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
            .help(L("editor_more"))

            Button { /* Favorite — placeholder per Photos parity. */ } label: {
                Image(systemName: "heart")
            }
            .buttonStyle(.borderless)
            .help(L("editor_favorite"))

            Button {
                // 0…3 CCW quarter-turns; counter-clockwise rotate cycles
                // forward through the field per `CropState.rotate90Quarter`.
                state.crop.rotate90Quarter = (state.crop.rotate90Quarter + 1) % 4
            } label: {
                Image(systemName: "arrow.counterclockwise")
            }
            .buttonStyle(.borderless)
            .help(L("editor_rotate"))

            Button {
                if let image = state.sourceImage ?? state.previewImage {
                    AutoEnhance.apply(target: .global, image: image, state: state)
                }
            } label: {
                Image(systemName: "wand.and.stars")
            }
            .buttonStyle(.borderless)
            .disabled(state.sourceImage == nil && state.previewImage == nil)
            .help(L("editor_enhance"))

            Button(action: onDone) {
                Text(L("editor_done"))
                    .font(.callout.weight(.semibold))
                    .padding(.horizontal, 14)
                    .padding(.vertical, 5)
                    .background(Color.yellow)
                    .foregroundStyle(Color.black)
                    .clipShape(Capsule())
            }
            .buttonStyle(.plain)
            .keyboardShortcut(.return, modifiers: [.command])
            .padding(.leading, 6)
        }
    }
}

/// Center pill of segmented tabs. Active tab has a darker rounded background
/// and bold text; inactive tabs are plain text. The pill is sized to its
/// content, NOT full width.
struct EditorPillTabs: View {
    @Binding var active: EditorTab

    var body: some View {
        HStack(spacing: 2) {
            ForEach(EditorTab.allCases, id: \.self) { tab in
                Button {
                    active = tab
                } label: {
                    Text(tab.localizedTitle)
                        .font(.callout.weight(active == tab ? .semibold : .regular))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 5)
                        .foregroundStyle(active == tab ? Color.primary : Color.secondary)
                        .background(
                            RoundedRectangle(cornerRadius: 8, style: .continuous)
                                .fill(active == tab
                                    ? Color.primary.opacity(0.16)
                                    : Color.clear)
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(
            Capsule()
                .fill(Color.primary.opacity(0.06))
        )
    }
}
