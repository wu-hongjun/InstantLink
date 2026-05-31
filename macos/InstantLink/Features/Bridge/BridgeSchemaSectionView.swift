import SwiftUI

/// Generic schema-driven settings renderer (plan 039 phase 1).
///
/// Takes a ``BridgeConfigSchema`` and the shared ``BridgeSettingsDraft``
/// and renders each field type to a SwiftUI primitive. The view never
/// references the typed ``BridgeAdjustmentsConfig`` directly — it speaks
/// only in the bridge's snake_case keys, going through the draft's
/// key adapter (``adjustmentsValue(forKey:)`` /
/// ``setAdjustmentsValue(_:forKey:)``).
///
/// Forward-compatibility: a field whose ``type`` the Mac doesn't know
/// (e.g. a future ``"color_picker"``) renders as a dimmed
/// "update InstantLink" placeholder rather than crashing.
struct BridgeSchemaSectionView: View {
    @ObservedObject var draft: BridgeSettingsDraft
    let schema: BridgeConfigSchema

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(Array(schema.fields.enumerated()), id: \.offset) { _, field in
                fieldView(field)
            }
        }
    }

    @ViewBuilder
    private func fieldView(_ field: BridgeConfigSchemaField) -> some View {
        let disabled = !isFieldEnabled(field)
        switch field {
        case .picker(let picker):
            pickerRow(picker)
                .disabled(disabled)
                .foregroundColor(disabled ? .secondary : .primary)
        case .slider(let slider):
            sliderRow(slider)
                .disabled(disabled)
                .foregroundColor(disabled ? .secondary : .primary)
        case .toggle(let toggle):
            toggleRow(toggle)
                .disabled(disabled)
                .foregroundColor(disabled ? .secondary : .primary)
        case .text(let text):
            textRow(text)
                .disabled(disabled)
                .foregroundColor(disabled ? .secondary : .primary)
        case .unknown(let key, let type):
            unknownRow(key: key, type: type)
        }
    }

    // MARK: - Picker

    private func pickerRow(_ field: BridgePickerField) -> some View {
        let binding = Binding<String>(
            get: {
                if let current = draft.adjustmentsValue(forKey: field.key) as? String {
                    return current
                }
                return field.options.first?.value ?? ""
            },
            set: { newValue in
                draft.setAdjustmentsValue(newValue, forKey: field.key)
            }
        )
        return HStack(spacing: 10) {
            Text(L(field.label))
                .font(.callout)
                .frame(width: 160, alignment: .leading)
            Picker("", selection: binding) {
                ForEach(field.options, id: \.value) { option in
                    Text(L(option.label)).tag(option.value)
                }
            }
            .labelsHidden()
            .pickerStyle(.menu)
            Spacer()
        }
    }

    // MARK: - Slider

    private func sliderRow(_ field: BridgeSliderField) -> some View {
        let intBinding = Binding<Int>(
            get: {
                if let current = draft.adjustmentsValue(forKey: field.key) as? Int {
                    return current
                }
                return Int(field.range.min)
            },
            set: { newValue in
                draft.setAdjustmentsValue(newValue, forKey: field.key)
            }
        )
        let doubleBinding = Binding<Double>(
            get: { Double(intBinding.wrappedValue) },
            set: { intBinding.wrappedValue = Int($0.rounded()) }
        )
        return HStack(spacing: 10) {
            Text(L(field.label))
                .font(.callout)
                .frame(width: 160, alignment: .leading)
            Slider(
                value: doubleBinding,
                in: field.range.min...field.range.max,
                step: field.range.step
            )
            Text(formatSliderBadge(value: intBinding.wrappedValue, display: field.display))
                .font(.callout.monospacedDigit())
                .foregroundColor(.secondary)
                .frame(width: 44, alignment: .trailing)
        }
    }

    private func formatSliderBadge(value: Int, display: BridgeSliderDisplay) -> String {
        switch display {
        case .signedPercent:
            if value > 0 { return "+\(value)" }
            return "\(value)"
        case .unsignedPercent, .integer:
            return "\(value)"
        }
    }

    // MARK: - Toggle

    private func toggleRow(_ field: BridgeToggleField) -> some View {
        let binding = Binding<Bool>(
            get: { (draft.adjustmentsValue(forKey: field.key) as? Bool) ?? false },
            set: { newValue in draft.setAdjustmentsValue(newValue, forKey: field.key) }
        )
        return Toggle(L(field.label), isOn: binding)
    }

    // MARK: - Text

    private func textRow(_ field: BridgeTextField) -> some View {
        let binding = Binding<String>(
            get: { (draft.adjustmentsValue(forKey: field.key) as? String) ?? "" },
            set: { newValue in draft.setAdjustmentsValue(newValue, forKey: field.key) }
        )
        return HStack(spacing: 10) {
            Text(L(field.label))
                .font(.callout)
                .frame(width: 160, alignment: .leading)
            TextField("", text: binding)
                .textFieldStyle(.roundedBorder)
            Spacer()
        }
    }

    // MARK: - Unknown field placeholder

    private func unknownRow(key: String, type: String) -> some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle")
                .foregroundColor(.secondary)
            Text(L("Setting requires a newer InstantLink. Update the app to manage \(key)."))
                .font(.callout)
                .foregroundColor(.secondary)
            Spacer()
        }
        .accessibilityIdentifier("bridge.schema.unknownField.\(type)")
    }

    // MARK: - Dependency gating

    /// Resolve a field's dependency against the current draft. A field with
    /// no ``depends_on`` is always enabled. When the parent value doesn't
    /// equal the declared dependency value, the field renders disabled.
    private func isFieldEnabled(_ field: BridgeConfigSchemaField) -> Bool {
        guard let dependency = field.dependsOn else { return true }
        let parentValue = draft.adjustmentsValue(forKey: dependency.field)
        return matches(parentValue: parentValue, dependency: dependency.value)
    }

    private func matches(parentValue: Any?, dependency: BridgeJSONValue) -> Bool {
        switch dependency {
        case .bool(let expected):
            return (parentValue as? Bool) == expected
        case .string(let expected):
            return (parentValue as? String) == expected
        case .number(let expected):
            if let intValue = parentValue as? Int {
                return Double(intValue) == expected
            }
            if let doubleValue = parentValue as? Double {
                return doubleValue == expected
            }
            return false
        case .null:
            return parentValue == nil
        case .array, .object:
            return false
        }
    }
}
