import Foundation

/// Observable draft model for the Bridge Settings tab.
///
/// Owns:
///   * The last-fetched canonical ``BridgeConfig`` (``loaded``).
///   * An editable copy the user mutates (``draft``).
///   * A field-error map populated by client-side validation and / or by
///     the bridge's `config_validation_failed` response.
///   * The Apply lifecycle state (idle / applying / succeeded / failed).
///
/// The view binds typed controls (Picker, Stepper, Toggle, TextField) to
/// nested fields under `draft`. When the user clicks "Apply", the view
/// calls `validate()`, builds a diff, and submits it through the
/// coordinator; on success it calls `load(_:)` again with the bridge's
/// fresh canonical state.
@MainActor
final class BridgeSettingsDraft: ObservableObject {
    /// Apply-button lifecycle. Used by the action bar to swap between
    /// idle / spinner / green-toast / red-error chrome without forcing
    /// the view to track its own boolean flags.
    enum ApplyState: Equatable {
        case idle
        case applying
        case succeeded(at: Date)
        case failed(message: String)

        var isApplying: Bool {
            if case .applying = self { return true }
            return false
        }
    }

    @Published private(set) var loaded: BridgeConfig?
    @Published var draft: BridgeConfig?
    @Published private(set) var fieldErrors: [BridgeConfigField: String] = [:]
    @Published private(set) var applyState: ApplyState = .idle
    /// Adjustments schema fetched from the bridge (plan 039 phase 1).
    /// ``nil`` until ``loadAdjustmentsSchema(_:)`` runs successfully; the
    /// Schema renderer reads this to drive the Adjustments card. When the
    /// fetch fails the section falls back to a hand-written card.
    @Published var adjustmentsSchema: BridgeConfigSchema?

    init(loaded: BridgeConfig? = nil) {
        self.loaded = loaded
        self.draft = loaded
    }

    // MARK: - Schema loading

    /// Replace the cached Adjustments schema. Pass ``nil`` to drop the cache
    /// (e.g. when the bridge endpoint failed and the UI should fall back).
    func loadAdjustmentsSchema(_ schema: BridgeConfigSchema?) {
        adjustmentsSchema = schema
    }

    // MARK: - Lifecycle

    /// Replace both ``loaded`` and ``draft`` with a freshly-fetched config
    /// and clear errors / apply state.
    func load(_ config: BridgeConfig) {
        loaded = config
        draft = config
        fieldErrors = [:]
        applyState = .idle
    }

    /// Revert in-memory edits back to the last loaded canonical state.
    func revert() {
        draft = loaded
        fieldErrors = [:]
        if case .failed = applyState {
            applyState = .idle
        }
    }

    /// True when the draft diverges from the last loaded canonical state.
    var isDirty: Bool {
        guard let loaded, let draft else { return false }
        return loaded != draft
    }

    // MARK: - Apply state transitions

    func beginApplying() {
        applyState = .applying
    }

    func recordApplySuccess(_ config: BridgeConfig, at date: Date = Date()) {
        load(config)
        applyState = .succeeded(at: date)
    }

    func recordApplyFailure(message: String, fieldErrors: [String: String] = [:]) {
        let mapped = Self.mapFieldErrors(fieldErrors)
        self.fieldErrors = mapped
        applyState = .failed(message: message)
    }

    // MARK: - Validation + diff

    /// Run client-side validation against ``draft``. Populates
    /// ``fieldErrors`` and returns ``true`` when no errors were raised.
    @discardableResult
    func validate() -> Bool {
        guard let draft else {
            fieldErrors = [:]
            return true
        }
        var errors: [BridgeConfigField: String] = [:]
        if draft.printer.quality < 1 || draft.printer.quality > 100 {
            errors[.printerJPEGQuality] = "JPEG quality must be between 1 and 100."
        }
        if !draft.printer.keepaliveIntervalSeconds.isFinite || draft.printer.keepaliveIntervalSeconds <= 0 {
            errors[.printerKeepaliveInterval] = "Keepalive interval must be greater than 0."
        }
        if !draft.printer.searchIntervalSeconds.isFinite || draft.printer.searchIntervalSeconds <= 0 {
            errors[.printerSearchInterval] = "Search interval must be greater than 0."
        }
        if let delay = draft.workflow.autoPrintDelaySeconds, delay != 0, delay != 5 {
            errors[.workflowAutoPrintDelay] = "Auto-print delay must be 0 s, 5 s, or Off."
        }
        if draft.power.idlePoweroffEnabled {
            if !draft.power.idlePoweroffAfterSeconds.isFinite || draft.power.idlePoweroffAfterSeconds <= 0 {
                errors[.powerIdlePoweroffAfter] = "Idle poweroff timer must be greater than 0."
            }
        }
        if draft.ftp.username.trimmingCharacters(in: .whitespaces).isEmpty {
            errors[.ftpUsername] = "FTP username is required."
        }
        if !BridgeAdjustmentsConfig.allPresetNames.contains(draft.adjustments.preset) {
            errors[.adjustmentsPreset] = "Unknown preset."
        }
        // Slider range validation reads from the loaded schema when
        // available; falls back to the hardcoded defaults so validation
        // still runs before the schema has been fetched. The bridge owns
        // the source of truth — when it tightens a range, the Mac
        // automatically respects it.
        let signedAxes: [(BridgeConfigField, String, Int)] = [
            (.adjustmentsSaturation, "saturation", draft.adjustments.saturation),
            (.adjustmentsExposure, "exposure", draft.adjustments.exposure),
            (.adjustmentsSharpness, "sharpness", draft.adjustments.sharpness),
            (.adjustmentsHue, "hue", draft.adjustments.hue),
        ]
        for (field, key, value) in signedAxes {
            let range = sliderRange(forKey: key, fallback: -100...100)
            if value < range.lowerBound || value > range.upperBound {
                errors[field] = "Must be between \(range.lowerBound) and \(range.upperBound)"
            }
        }
        let vignetteRange = sliderRange(forKey: "vignette", fallback: 0...100)
        if draft.adjustments.vignette < vignetteRange.lowerBound
            || draft.adjustments.vignette > vignetteRange.upperBound
        {
            errors[.adjustmentsVignette] = "Must be between \(vignetteRange.lowerBound) and \(vignetteRange.upperBound)"
        }
        fieldErrors = errors
        return errors.isEmpty
    }

    /// Build the JSON-encodable diff payload to send to `PUT /v1/config`.
    ///
    /// Returns a dictionary shaped ``[section: [field: value]]``. Sections
    /// whose fields are all unchanged are omitted; unchanged fields within
    /// a changed section are also omitted. The result is intentionally a
    /// plain JSON-compatible value tree so the transport can encode it
    /// with ``JSONSerialization``.
    func diff() -> [String: Any] {
        guard let loaded, let draft else { return [:] }
        var payload: [String: Any] = [:]
        var ftp: [String: Any] = [:]
        if loaded.ftp.mode != draft.ftp.mode {
            ftp["mode"] = draft.ftp.mode.rawValue
        }
        if loaded.ftp.username != draft.ftp.username {
            ftp["username"] = draft.ftp.username
        }
        if let pending = pendingPassword, !pending.isEmpty {
            ftp["password"] = pending
        }
        if !ftp.isEmpty {
            payload["ftp"] = ftp
        }

        var printer: [String: Any] = [:]
        if loaded.printer.model != draft.printer.model {
            printer["model"] = draft.printer.model
        }
        if loaded.printer.fit != draft.printer.fit {
            printer["fit"] = draft.printer.fit
        }
        if loaded.printer.quality != draft.printer.quality {
            printer["quality"] = draft.printer.quality
        }
        if loaded.printer.keepaliveIntervalSeconds != draft.printer.keepaliveIntervalSeconds {
            printer["keepalive_interval_s"] = draft.printer.keepaliveIntervalSeconds
        }
        if loaded.printer.searchIntervalSeconds != draft.printer.searchIntervalSeconds {
            printer["search_interval_s"] = draft.printer.searchIntervalSeconds
        }
        if !printer.isEmpty {
            payload["printer"] = printer
        }

        var workflow: [String: Any] = [:]
        if loaded.workflow.autoPrintDelaySeconds != draft.workflow.autoPrintDelaySeconds {
            if let value = draft.workflow.autoPrintDelaySeconds {
                workflow["auto_print_delay_s"] = value
            } else {
                workflow["auto_print_delay_s"] = "off"
            }
        }
        if loaded.workflow.allowPrintWithoutFilm != draft.workflow.allowPrintWithoutFilm {
            workflow["allow_print_without_film"] = draft.workflow.allowPrintWithoutFilm
        }
        if !workflow.isEmpty {
            payload["workflow"] = workflow
        }

        var power: [String: Any] = [:]
        if loaded.power.idlePoweroffEnabled != draft.power.idlePoweroffEnabled {
            power["idle_poweroff_enabled"] = draft.power.idlePoweroffEnabled
        }
        if loaded.power.idlePoweroffAfterSeconds != draft.power.idlePoweroffAfterSeconds {
            power["idle_poweroff_after_s"] = draft.power.idlePoweroffAfterSeconds
        }
        if !power.isEmpty {
            payload["power"] = power
        }

        var ui: [String: Any] = [:]
        if loaded.ui.appearance != draft.ui.appearance {
            ui["appearance"] = draft.ui.appearance.rawValue
        }
        if loaded.ui.fontSize != draft.ui.fontSize {
            ui["font_size"] = draft.ui.fontSize.rawValue
        }
        if loaded.ui.language != draft.ui.language {
            ui["language"] = draft.ui.language.rawValue
        }
        if !ui.isEmpty {
            payload["ui"] = ui
        }

        var adjustments: [String: Any] = [:]
        if loaded.adjustments.preset != draft.adjustments.preset {
            adjustments["preset"] = draft.adjustments.preset
        }
        if loaded.adjustments.saturation != draft.adjustments.saturation {
            adjustments["saturation"] = draft.adjustments.saturation
        }
        if loaded.adjustments.exposure != draft.adjustments.exposure {
            adjustments["exposure"] = draft.adjustments.exposure
        }
        if loaded.adjustments.sharpness != draft.adjustments.sharpness {
            adjustments["sharpness"] = draft.adjustments.sharpness
        }
        if loaded.adjustments.hue != draft.adjustments.hue {
            adjustments["hue"] = draft.adjustments.hue
        }
        if loaded.adjustments.vignette != draft.adjustments.vignette {
            adjustments["vignette"] = draft.adjustments.vignette
        }
        if loaded.adjustments.datestamp != draft.adjustments.datestamp {
            adjustments["datestamp"] = draft.adjustments.datestamp
        }
        if loaded.adjustments.datestampFormat != draft.adjustments.datestampFormat {
            adjustments["datestamp_format"] = draft.adjustments.datestampFormat.rawValue
        }
        if loaded.adjustments.watermark != draft.adjustments.watermark {
            adjustments["watermark"] = draft.adjustments.watermark
        }
        if loaded.adjustments.watermarkText != draft.adjustments.watermarkText {
            adjustments["watermark_text"] = draft.adjustments.watermarkText
        }
        if !adjustments.isEmpty {
            payload["adjustments"] = adjustments
        }

        return payload
    }

    // MARK: - Cleartext-only fields (not held inside `draft`)

    /// Pending FTP password. The cleartext value lives outside ``draft``
    /// because the bridge never returns it; we only ship it on Apply when
    /// the user explicitly typed a new value.
    @Published var pendingPassword: String?

    var isDirtyIncludingPassword: Bool {
        if let pending = pendingPassword, !pending.isEmpty { return true }
        return isDirty
    }

    // MARK: - Schema key adapter (plan 039 phase 1)

    /// Read the current draft value for one Adjustments field by its
    /// bridge-side snake_case key. Returns ``nil`` for unknown keys so the
    /// schema renderer can show its "unsupported field" placeholder.
    func adjustmentsValue(forKey key: String) -> Any? {
        guard let draft else { return nil }
        switch key {
        case "preset": return draft.adjustments.preset
        case "saturation": return draft.adjustments.saturation
        case "exposure": return draft.adjustments.exposure
        case "sharpness": return draft.adjustments.sharpness
        case "hue": return draft.adjustments.hue
        case "vignette": return draft.adjustments.vignette
        case "datestamp": return draft.adjustments.datestamp
        case "datestamp_format": return draft.adjustments.datestampFormat.rawValue
        case "watermark": return draft.adjustments.watermark
        case "watermark_text": return draft.adjustments.watermarkText
        default: return nil
        }
    }

    /// Write a draft value back through the bridge-side snake_case key.
    /// Unknown keys are silently dropped — forward-compat with future
    /// bridge-only fields the Mac is too old to understand.
    func setAdjustmentsValue(_ value: Any, forKey key: String) {
        guard var current = draft else { return }
        switch key {
        case "preset":
            if let stringValue = value as? String {
                current.adjustments.preset = stringValue
            }
        case "saturation":
            if let intValue = coerceInt(value) {
                current.adjustments.saturation = intValue
            }
        case "exposure":
            if let intValue = coerceInt(value) {
                current.adjustments.exposure = intValue
            }
        case "sharpness":
            if let intValue = coerceInt(value) {
                current.adjustments.sharpness = intValue
            }
        case "hue":
            if let intValue = coerceInt(value) {
                current.adjustments.hue = intValue
            }
        case "vignette":
            if let intValue = coerceInt(value) {
                current.adjustments.vignette = intValue
            }
        case "datestamp":
            if let boolValue = value as? Bool {
                current.adjustments.datestamp = boolValue
            }
        case "datestamp_format":
            if let stringValue = value as? String,
               let parsed = BridgeDatestampFormat(rawValue: stringValue) {
                current.adjustments.datestampFormat = parsed
            }
        case "watermark":
            if let boolValue = value as? Bool {
                current.adjustments.watermark = boolValue
            }
        case "watermark_text":
            if let stringValue = value as? String {
                current.adjustments.watermarkText = stringValue
            }
        default:
            return
        }
        draft = current
    }

    private func coerceInt(_ value: Any) -> Int? {
        if let intValue = value as? Int { return intValue }
        if let doubleValue = value as? Double { return Int(doubleValue.rounded()) }
        return nil
    }

    /// Resolve the slider's integer range for a given key from the loaded
    /// schema, falling back to the supplied default when the schema isn't
    /// loaded or doesn't declare the field.
    func sliderRange(forKey key: String, fallback: ClosedRange<Int>) -> ClosedRange<Int> {
        guard let schema = adjustmentsSchema else { return fallback }
        for field in schema.fields {
            if case .slider(let slider) = field, slider.key == key {
                let low = Int(slider.range.min.rounded())
                let high = Int(slider.range.max.rounded())
                guard low <= high else { return fallback }
                return low...high
            }
        }
        return fallback
    }

    // MARK: - Helpers

    private static func mapFieldErrors(_ raw: [String: String]) -> [BridgeConfigField: String] {
        var mapped: [BridgeConfigField: String] = [:]
        for (key, value) in raw {
            if let field = BridgeConfigField(rawValue: key) {
                mapped[field] = value
            }
        }
        return mapped
    }
}
