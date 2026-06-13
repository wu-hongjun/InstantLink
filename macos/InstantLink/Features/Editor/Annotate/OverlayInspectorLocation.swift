import SwiftUI

/// Per-kind inspector content for a Location overlay. Ported from
/// `SelectedOverlayInspectorView.locationControls` in the retired legacy
/// editor. Uses the ViewModel's `imageLocation` so source/photo-metadata mode
/// can surface "no location metadata" if the image has no GPS EXIF.
struct OverlayInspectorLocation: View {
    @ObservedObject var state: EditorViewState
    @EnvironmentObject var viewModel: ViewModel
    let overlay: OverlayItem

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Picker(L("Source"), selection: Binding(
                get: { data.source },
                set: { newValue in
                    update {
                        $0.source = newValue
                        if newValue == .manualText {
                            $0.displayStyle = .name
                        }
                    }
                }
            )) {
                Text(L("Photo Metadata")).tag(LocationOverlaySource.photoMetadata)
                Text(L("Manual Coordinates")).tag(LocationOverlaySource.manualCoordinates)
                Text(L("Manual Text")).tag(LocationOverlaySource.manualText)
            }
            .pickerStyle(.menu)

            if data.source != .manualText {
                Picker(L("Display"), selection: Binding(
                    get: { data.displayStyle },
                    set: { newValue in update { $0.displayStyle = newValue } }
                )) {
                    Text(L("Coordinates")).tag(LocationOverlayDisplayStyle.coordinates)
                    Text(L("Name")).tag(LocationOverlayDisplayStyle.name)
                    Text(L("Name + Coordinates")).tag(LocationOverlayDisplayStyle.nameAndCoordinates)
                }
                .pickerStyle(.menu)
            }

            switch data.source {
            case .photoMetadata:
                if viewModel.imageLocation == nil {
                    Text(L("No location metadata"))
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                if data.displayStyle != .coordinates {
                    nameField(title: L("Name"))
                }
                if data.displayStyle != .name {
                    precisionSlider
                }

            case .manualCoordinates:
                if data.displayStyle != .coordinates {
                    nameField(title: L("Name"))
                }
                HStack {
                    coordinateField(title: L("Latitude"), axis: .latitude)
                    coordinateField(title: L("Longitude"), axis: .longitude)
                }
                if data.displayStyle != .name {
                    precisionSlider
                }

            case .manualText:
                nameField(title: L("Content"))
            }
        }
    }

    private var data: LocationOverlayData {
        if case .location(let value) = overlay.content { return value }
        return LocationOverlayData()
    }

    private var precisionSlider: some View {
        let binding = Binding<Double>(
            get: { Double(data.precision) },
            set: { newValue in update { $0.precision = Int(newValue.rounded()) } }
        )
        return VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(L("Precision"))
                    .font(.caption)
                    .foregroundColor(.secondary)
                Spacer()
                Text("\(Int(binding.wrappedValue.rounded()))")
                    .font(.caption.monospacedDigit())
                    .foregroundColor(.secondary)
            }
            Slider(value: binding, in: 0...6, step: 1)
                .controlSize(.small)
        }
    }

    private func nameField(title: String) -> some View {
        TextField(title, text: Binding(
            get: { data.locationName },
            set: { newValue in update { $0.locationName = newValue } }
        ))
    }

    private enum CoordinateAxis { case latitude, longitude }

    private func coordinateField(title: String, axis: CoordinateAxis) -> some View {
        TextField(title, text: Binding(
            get: {
                switch axis {
                case .latitude:
                    guard let value = data.coordinate?.latitude else { return "" }
                    return String(value)
                case .longitude:
                    guard let value = data.coordinate?.longitude else { return "" }
                    return String(value)
                }
            },
            set: { newValue in
                update { data in
                    let latitude = axis == .latitude
                        ? (Double(newValue) ?? data.coordinate?.latitude ?? 0)
                        : (data.coordinate?.latitude ?? 0)
                    let longitude = axis == .longitude
                        ? (Double(newValue) ?? data.coordinate?.longitude ?? 0)
                        : (data.coordinate?.longitude ?? 0)
                    data.coordinate = GeoCoordinate(latitude: latitude, longitude: longitude)
                }
            }
        ))
    }

    private func update(_ mutate: (inout LocationOverlayData) -> Void) {
        state.updateOverlay(id: overlay.id) { item in
            guard case .location(var data) = item.content else { return }
            mutate(&data)
            item.content = .location(data)
        }
    }
}
