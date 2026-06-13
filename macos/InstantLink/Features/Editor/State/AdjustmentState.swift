import CoreGraphics
import Foundation

/// Full per-image adjustment model. All sliders are Double in [-1, +1] (snap to
/// 0 = neutral) unless noted otherwise. Per-section enabled flag lets a section
/// be muted without losing the user's values.
struct AdjustmentState: Equatable, Codable {

    // MARK: White Balance
    struct WhiteBalance: Equatable, Codable {
        enum Mode: String, Codable { case neutralGray, skinTone, temperatureTint }
        var mode: Mode = .temperatureTint
        var temperature: Double = 0
        var tint: Double = 0
        var eyedropPoint: CGPoint?
        var eyedropSample: SampledRGB?
        var sectionEnabled: Bool = true
    }

    // MARK: Light
    struct Light: Equatable, Codable {
        var brilliance: Double = 0
        var exposure: Double = 0
        var highlights: Double = 0
        var shadows: Double = 0
        var brightness: Double = 0
        var contrast: Double = 0
        var blackPoint: Double = 0
        var sectionEnabled: Bool = true
    }

    // MARK: Color
    struct Color: Equatable, Codable {
        var saturation: Double = 0
        var vibrance: Double = 0
        var cast: Double = 0
        var sectionEnabled: Bool = true
    }

    // MARK: Black & White
    struct BlackAndWhite: Equatable, Codable {
        var on: Bool = false
        var intensity: Double = 0
        var neutrals: Double = 0
        var tone: Double = 0
        var grain: Double = 0
        var sectionEnabled: Bool = true
    }

    // MARK: Curves
    struct Curves: Equatable, Codable {
        var master: [CGPoint] = AdjustmentState.identityCurvePoints
        var red: [CGPoint] = AdjustmentState.identityCurvePoints
        var green: [CGPoint] = AdjustmentState.identityCurvePoints
        var blue: [CGPoint] = AdjustmentState.identityCurvePoints
        var sectionEnabled: Bool = true
    }

    // MARK: Levels (per-channel — plan 048 PR #5)
    struct Levels: Equatable, Codable {
        /// Channel selector — Levels uniquely exposes Luminance vs Curves.
        enum Channel: String, Codable, CaseIterable {
            case luminance
            case rgb
            case red
            case green
            case blue
        }

        /// Per-channel handle positions. 5 bottom handles (Black / Shadows /
        /// Mid / Highlights / White) + 2 top handles (output Black / White).
        struct ChannelLevels: Equatable, Codable {
            var blackIn: Double = 0
            var shadows: Double = 0.25
            var gamma: Double = 1
            var highlights: Double = 0.75
            var whiteIn: Double = 1
            var blackOut: Double = 0
            var whiteOut: Double = 1

            static let neutral = ChannelLevels()

            var isNeutral: Bool {
                blackIn == 0 && shadows == 0.25 && gamma == 1 && highlights == 0.75
                    && whiteIn == 1 && blackOut == 0 && whiteOut == 1
            }
        }

        var activeChannel: Channel = .luminance
        var channels: [Channel: ChannelLevels] = Dictionary(
            uniqueKeysWithValues: Channel.allCases.map { ($0, ChannelLevels()) }
        )
        var sectionEnabled: Bool = true

        var isNeutral: Bool {
            channels.values.allSatisfy { $0.isNeutral }
        }

        // MARK: Codable backward compatibility
        //
        // PR #1 persisted snapshots may carry the old single-triplet shape:
        //   blackIn / whiteIn / gamma / blackOut / whiteOut + sectionEnabled.
        // The synthesized decoder would throw on missing `activeChannel` /
        // `channels` keys, so we hand-roll one that recognises either shape
        // and writes the legacy values into `Channel.luminance` defaults.
        private enum CodingKeys: String, CodingKey {
            case activeChannel, channels, sectionEnabled
            // Legacy keys (PR #1 shape):
            case blackIn, whiteIn, gamma, blackOut, whiteOut
        }

        init() {}

        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            self.sectionEnabled = try c.decodeIfPresent(Bool.self, forKey: .sectionEnabled) ?? true

            if let storedChannels = try c.decodeIfPresent([Channel: ChannelLevels].self, forKey: .channels) {
                // New per-channel shape.
                self.activeChannel = try c.decodeIfPresent(Channel.self, forKey: .activeChannel) ?? .luminance
                var merged = Dictionary(uniqueKeysWithValues: Channel.allCases.map { ($0, ChannelLevels()) })
                for (k, v) in storedChannels { merged[k] = v }
                self.channels = merged
            } else {
                // Legacy single-triplet shape — fold into Luminance, leave the
                // other channels at default.
                var lum = ChannelLevels()
                if let v = try c.decodeIfPresent(Double.self, forKey: .blackIn) { lum.blackIn = v }
                if let v = try c.decodeIfPresent(Double.self, forKey: .whiteIn) { lum.whiteIn = v }
                if let v = try c.decodeIfPresent(Double.self, forKey: .gamma) { lum.gamma = v }
                if let v = try c.decodeIfPresent(Double.self, forKey: .blackOut) { lum.blackOut = v }
                if let v = try c.decodeIfPresent(Double.self, forKey: .whiteOut) { lum.whiteOut = v }
                self.activeChannel = .luminance
                var merged = Dictionary(uniqueKeysWithValues: Channel.allCases.map { ($0, ChannelLevels()) })
                merged[.luminance] = lum
                self.channels = merged
            }
        }

        func encode(to encoder: Encoder) throws {
            var c = encoder.container(keyedBy: CodingKeys.self)
            try c.encode(activeChannel, forKey: .activeChannel)
            try c.encode(channels, forKey: .channels)
            try c.encode(sectionEnabled, forKey: .sectionEnabled)
        }
    }

    // MARK: Definition (single slider per locked decision Q7)
    struct Definition: Equatable, Codable {
        var amount: Double = 0
        var sectionEnabled: Bool = true
    }

    // MARK: Selective Color (6 user-defined wells per locked decision Q6)
    struct SelectiveColor: Equatable, Codable {
        static let maxWells = 6

        struct Well: Equatable, Codable {
            var seed: CodableColor?
            var range: Double = 0.5
            var hue: Double = 0
            var saturation: Double = 0
            var luminance: Double = 0
        }

        var wells: [Well] = Array(repeating: Well(), count: SelectiveColor.maxWells)
        var sectionEnabled: Bool = true
    }

    // MARK: Noise Reduction
    struct NoiseReduction: Equatable, Codable {
        var master: Double = 0
        var luma: Double = 0
        var color: Double = 0
        var detail: Double = 0
        var sectionEnabled: Bool = true
    }

    // MARK: Sharpen
    struct Sharpen: Equatable, Codable {
        var intensity: Double = 0
        var edges: Double = 0.22
        var falloff: Double = 0.69
        var sectionEnabled: Bool = true
    }

    // MARK: Vignette (Strength / Radius / Softness per locked decision)
    struct Vignette: Equatable, Codable {
        var strength: Double = 0
        var radius: Double = 0.5
        var softness: Double = 0.5
        var sectionEnabled: Bool = true
    }

    // MARK: Red Eye
    struct RedEyeCorrection: Equatable, Codable {
        var point: CGPoint
        var radius: Double
    }

    struct RedEye: Equatable, Codable {
        var corrections: [RedEyeCorrection] = []
        var size: Double = 24
        var sectionEnabled: Bool = true
    }

    // MARK: Sections
    var whiteBalance = WhiteBalance()
    var light = Light()
    var color = Color()
    var bw = BlackAndWhite()
    var curves = Curves()
    var levels = Levels()
    var definition = Definition()
    var selective = SelectiveColor()
    var nr = NoiseReduction()
    var sharpen = Sharpen()
    var vignette = Vignette()
    var redEye = RedEye()

    static let neutral = AdjustmentState()

    static let identityCurvePoints: [CGPoint] = [
        CGPoint(x: 0, y: 0),
        CGPoint(x: 0.25, y: 0.25),
        CGPoint(x: 0.5, y: 0.5),
        CGPoint(x: 0.75, y: 0.75),
        CGPoint(x: 1, y: 1),
    ]
}

/// Codable RGB color used for serializable Selective Color seeds.
struct CodableColor: Equatable, Codable {
    var red: Double
    var green: Double
    var blue: Double
    var alpha: Double = 1
}

/// Codable sampled pixel used for stored eyedropper results.
struct SampledRGB: Equatable, Codable {
    var red: Double
    var green: Double
    var blue: Double
}
