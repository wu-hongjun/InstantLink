import SwiftUI

/// Per-kind inspector content for a Timestamp overlay. Ported from
/// `SelectedOverlayInspectorView.timestampControls` in the retired legacy
/// editor; the format-selection lock and the line-2 chain on Time Line are
/// preserved verbatim from `TimestampPresetCatalog`.
struct OverlayInspectorTimestamp: View {
    @ObservedObject var state: EditorViewState
    let overlay: OverlayItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RoundedRectangle(cornerRadius: 6)
                .fill(Color.white.opacity(0.05))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.white.opacity(0.14), lineWidth: 1)
                )
                .frame(height: 48)
                .overlay {
                    TimestampPreviewView(data: data, size: CGSize(width: 200, height: 48))
                }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    ForEach(TimestampPresetCatalog.presetOrder, id: \.self) { key in
                        PresetCard(
                            preset: TimestampPresetCatalog.presets[key]!,
                            isSelected: data.presetKey == key
                        )
                        .onTapGesture {
                            update {
                                $0.presetKey = key
                                $0.lightBleedEnabled = TimestampPresetCatalog.presets[key]!.defaultLightBleed
                            }
                        }
                    }
                }
            }

            if allowsFormatSelection {
                Picker(L("Format"), selection: Binding(
                    get: { data.format },
                    set: { newValue in update { $0.format = newValue } }
                )) {
                    Text("YY.MM.DD").tag(TimestampFormat.ymd)
                    Text("MM.DD.YY").tag(TimestampFormat.mdy)
                    Text("DD.MM.YY").tag(TimestampFormat.dmy)
                }
                .pickerStyle(.segmented)
            }

            HStack {
                Toggle(L("Time Line"), isOn: Binding(
                    get: { data.showsTime },
                    set: { newValue in update { $0.showsTime = newValue } }
                ))
                Toggle(L("Glow"), isOn: Binding(
                    get: { data.lightBleedEnabled },
                    set: { newValue in update { $0.lightBleedEnabled = newValue } }
                ))
            }
            .font(.caption)

            HStack {
                Toggle(L("Show Seconds"), isOn: Binding(
                    get: { data.showsSeconds },
                    set: { newValue in update { $0.showsSeconds = newValue } }
                ))
                .disabled(!data.showsTime)

                Toggle(L("One Line"), isOn: Binding(
                    get: { data.singleLine },
                    set: { newValue in update { $0.singleLine = newValue } }
                ))
                .disabled(!data.showsTime)
            }
            .font(.caption)
        }
    }

    private var data: TimestampOverlayData {
        if case .timestamp(let value) = overlay.content { return value }
        return TimestampOverlayData()
    }

    private var allowsFormatSelection: Bool {
        guard let preset = TimestampPresetCatalog.presets[data.presetKey] else { return true }
        return preset.layout.allowsFormatSelection
    }

    private func update(_ mutate: (inout TimestampOverlayData) -> Void) {
        state.updateOverlay(id: overlay.id) { item in
            guard case .timestamp(var data) = item.content else { return }
            mutate(&data)
            item.content = .timestamp(data)
        }
    }
}
