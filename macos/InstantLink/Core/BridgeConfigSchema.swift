import Foundation

/// Schema descriptor for a settings section returned by the bridge.
///
/// Plan 039 phase 1: the bridge owns the field shapes for the Adjustments
/// section (`GET /v1/config/schema/adjustments`); the Mac renders a generic
/// SwiftUI form from this schema rather than mirroring every field by hand.
struct BridgeConfigSchema: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let section: String
    let title: String
    let fields: [BridgeConfigSchemaField]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case section
        case title
        case fields
    }
}

/// One field of a settings schema. Forward-compatible: a field type the
/// Mac doesn't know about (e.g. a future ``color_picker``) decodes as
/// ``unknown(key:type:)`` so the UI can render a "Update InstantLink"
/// placeholder instead of crashing.
enum BridgeConfigSchemaField: Codable, Equatable, Sendable {
    case picker(BridgePickerField)
    case slider(BridgeSliderField)
    case toggle(BridgeToggleField)
    case text(BridgeTextField)
    case unknown(key: String, type: String)

    /// Stable key the bridge uses for this field (matches the dataclass
    /// field name, e.g. ``"saturation"``).
    var key: String {
        switch self {
        case .picker(let field): return field.key
        case .slider(let field): return field.key
        case .toggle(let field): return field.key
        case .text(let field): return field.key
        case .unknown(let key, _): return key
        }
    }

    /// Optional dependency on another field (e.g. ``datestamp_format``
    /// depends on ``datestamp == true``). ``nil`` for sliders / toggles /
    /// fields with no parent.
    var dependsOn: BridgeFieldDependency? {
        switch self {
        case .picker(let field): return field.dependsOn
        case .text(let field): return field.dependsOn
        case .slider, .toggle, .unknown: return nil
        }
    }

    private enum TypeKey: String, CodingKey { case type, key }
    private enum FieldType: String { case picker, slider, toggle, text }

    init(from decoder: Decoder) throws {
        let header = try decoder.container(keyedBy: TypeKey.self)
        let typeString = try header.decode(String.self, forKey: .type)
        let single = try decoder.singleValueContainer()
        switch FieldType(rawValue: typeString) {
        case .picker:
            self = .picker(try single.decode(BridgePickerField.self))
        case .slider:
            self = .slider(try single.decode(BridgeSliderField.self))
        case .toggle:
            self = .toggle(try single.decode(BridgeToggleField.self))
        case .text:
            self = .text(try single.decode(BridgeTextField.self))
        case .none:
            let key = try header.decode(String.self, forKey: .key)
            self = .unknown(key: key, type: typeString)
        }
    }

    func encode(to encoder: Encoder) throws {
        var single = encoder.singleValueContainer()
        switch self {
        case .picker(let field):
            try single.encode(BridgeTypedField(type: "picker", payload: field))
        case .slider(let field):
            try single.encode(BridgeTypedField(type: "slider", payload: field))
        case .toggle(let field):
            try single.encode(BridgeTypedField(type: "toggle", payload: field))
        case .text(let field):
            try single.encode(BridgeTypedField(type: "text", payload: field))
        case .unknown(let key, let typeString):
            try single.encode(BridgeUnknownTypedField(type: typeString, key: key))
        }
    }
}

private struct BridgeTypedField<Payload: Encodable & Equatable & Sendable>: Encodable {
    var type: String
    var payload: Payload

    private enum CodingKeys: String, CodingKey { case type }

    func encode(to encoder: Encoder) throws {
        try payload.encode(to: encoder)
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(type, forKey: .type)
    }
}

private struct BridgeUnknownTypedField: Encodable {
    var type: String
    var key: String
}

struct BridgePickerField: Codable, Equatable, Sendable {
    let key: String
    let label: String
    let help: String?
    let options: [BridgePickerOption]
    let dependsOn: BridgeFieldDependency?

    enum CodingKeys: String, CodingKey {
        case key, label, help, options
        case dependsOn = "depends_on"
    }
}

struct BridgePickerOption: Codable, Equatable, Sendable {
    let value: String
    let label: String
}

struct BridgeSliderField: Codable, Equatable, Sendable {
    let key: String
    let label: String
    let help: String?
    let range: BridgeSliderRange
    let display: BridgeSliderDisplay
}

struct BridgeSliderRange: Codable, Equatable, Sendable {
    let min: Double
    let max: Double
    let step: Double
}

enum BridgeSliderDisplay: String, Codable, Sendable {
    case signedPercent = "signed_percent"
    case unsignedPercent = "unsigned_percent"
    case integer
}

struct BridgeToggleField: Codable, Equatable, Sendable {
    let key: String
    let label: String
    let help: String?
}

struct BridgeTextField: Codable, Equatable, Sendable {
    let key: String
    let label: String
    let help: String?
    let dependsOn: BridgeFieldDependency?

    enum CodingKeys: String, CodingKey {
        case key, label, help
        case dependsOn = "depends_on"
    }
}

/// Declared dependency between two schema fields. When the parent
/// ``field`` doesn't equal ``value`` in the current draft, the dependent
/// field renders as disabled.
struct BridgeFieldDependency: Codable, Equatable, Sendable {
    let field: String
    let value: BridgeJSONValue
}
