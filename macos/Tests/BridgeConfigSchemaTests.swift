import Foundation

final class BridgeConfigSchemaTests {
    private static let allTypesFixture = """
    {
      "schema_version": 1,
      "section": "adjustments",
      "title": "Image adjustments",
      "fields": [
        {
          "key": "preset",
          "type": "picker",
          "label": "Preset",
          "help": "Choose a preset or Custom slot",
          "options": [
            {"value": "Default", "label": "Default"},
            {"value": "Vivid", "label": "Vivid"}
          ]
        },
        {
          "key": "saturation",
          "type": "slider",
          "label": "Saturation",
          "help": "Colour intensity",
          "range": {"min": -100, "max": 100, "step": 10},
          "display": "signed_percent"
        },
        {
          "key": "datestamp",
          "type": "toggle",
          "label": "Datestamp",
          "help": "Stamp the photo's date"
        },
        {
          "key": "datestamp_format",
          "type": "picker",
          "label": "Datestamp format",
          "depends_on": {"field": "datestamp", "value": true},
          "options": [
            {"value": "quartz_date", "label": "Quartz Date"},
            {"value": "olympus", "label": "Olympus"}
          ]
        },
        {
          "key": "watermark_text",
          "type": "text",
          "label": "Watermark text",
          "depends_on": {"field": "watermark", "value": true}
        }
      ]
    }
    """

    private static let unknownTypeFixture = """
    {
      "schema_version": 1,
      "section": "adjustments",
      "title": "Image adjustments",
      "fields": [
        {
          "key": "future_widget",
          "type": "color_picker",
          "label": "Future widget"
        }
      ]
    }
    """

    func testDecodesSchemaWithAllFieldTypes() throws {
        let data = try unwrap(Self.allTypesFixture.data(using: .utf8))
        let schema = try JSONDecoder().decode(BridgeConfigSchema.self, from: data)
        try expectEqual(schema.schemaVersion, 1)
        try expectEqual(schema.section, "adjustments")
        try expectEqual(schema.title, "Image adjustments")
        try expectEqual(schema.fields.count, 5)

        guard case .picker(let preset) = schema.fields[0] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected picker field at index 0")
        }
        try expectEqual(preset.key, "preset")
        try expectEqual(preset.label, "Preset")
        try expectEqual(preset.options.count, 2)
        try expectEqual(preset.options[0].value, "Default")
        try expectNil(preset.dependsOn)

        guard case .slider(let saturation) = schema.fields[1] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected slider field at index 1")
        }
        try expectEqual(saturation.range.min, -100)
        try expectEqual(saturation.range.max, 100)
        try expectEqual(saturation.range.step, 10)
        try expectEqual(saturation.display, .signedPercent)

        guard case .toggle(let datestamp) = schema.fields[2] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected toggle field at index 2")
        }
        try expectEqual(datestamp.key, "datestamp")
        try expectEqual(datestamp.label, "Datestamp")

        guard case .picker(let datestampFormat) = schema.fields[3] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected picker field at index 3")
        }
        try expectEqual(datestampFormat.key, "datestamp_format")
        let formatDependency = try unwrap(datestampFormat.dependsOn)
        try expectEqual(formatDependency.field, "datestamp")
        try expectEqual(formatDependency.value, .bool(true))

        guard case .text(let watermarkText) = schema.fields[4] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected text field at index 4")
        }
        try expectEqual(watermarkText.key, "watermark_text")
        let watermarkDependency = try unwrap(watermarkText.dependsOn)
        try expectEqual(watermarkDependency.field, "watermark")
        try expectEqual(watermarkDependency.value, .bool(true))
    }

    func testDecodesUnknownFieldTypeAsUnknownCase() throws {
        let data = try unwrap(Self.unknownTypeFixture.data(using: .utf8))
        let schema = try JSONDecoder().decode(BridgeConfigSchema.self, from: data)
        try expectEqual(schema.fields.count, 1)
        guard case .unknown(let key, let type) = schema.fields[0] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected unknown field")
        }
        try expectEqual(key, "future_widget")
        try expectEqual(type, "color_picker")
    }

    func testPickerDecodesOptionsAndDependsOn() throws {
        let data = try unwrap(Self.allTypesFixture.data(using: .utf8))
        let schema = try JSONDecoder().decode(BridgeConfigSchema.self, from: data)
        guard case .picker(let datestampFormat) = schema.fields[3] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected picker field at index 3")
        }
        try expectEqual(datestampFormat.options.count, 2)
        try expectEqual(datestampFormat.options[0].value, "quartz_date")
        try expectEqual(datestampFormat.options[0].label, "Quartz Date")
        let dependency = try unwrap(datestampFormat.dependsOn)
        try expectEqual(dependency.value, .bool(true))
    }

    func testSliderDecodesRangeAndDisplay() throws {
        let data = try unwrap(Self.allTypesFixture.data(using: .utf8))
        let schema = try JSONDecoder().decode(BridgeConfigSchema.self, from: data)
        guard case .slider(let saturation) = schema.fields[1] else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected slider field at index 1")
        }
        try expectEqual(saturation.key, "saturation")
        try expectEqual(saturation.range.min, -100)
        try expectEqual(saturation.range.max, 100)
        try expectEqual(saturation.range.step, 10)
        try expectEqual(saturation.display, .signedPercent)
        try expectEqual(saturation.help, "Colour intensity")
    }

    private func unwrap<T>(_ value: T?) throws -> T {
        guard let value else {
            throw MacTestFailure(file: #filePath, line: #line, message: "Expected non-nil value")
        }
        return value
    }
}
