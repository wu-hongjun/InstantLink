import CoreImage
import Foundation

final class EditorAdjustmentPipelineTests {
    func testBlackAndWhitePipelineSkipsWhenSectionDisabled() throws {
        let image = testInputImage()
        var state = AdjustmentState.BlackAndWhite()
        state.sectionEnabled = false
        state.on = true
        state.intensity = 0.5

        let output = BlackAndWhitePipeline.apply(image, state)

        try expectTrue(output === image)
    }

    func testBlackAndWhitePipelineAppliesWhenEnabledAndOn() throws {
        let image = testInputImage()
        var state = AdjustmentState.BlackAndWhite()
        state.sectionEnabled = true
        state.on = true
        state.intensity = 0.5

        let output = BlackAndWhitePipeline.apply(image, state)

        try expectFalse(output === image)
    }

    private func testInputImage() -> CIImage {
        CIImage(color: CIColor(red: 0.2, green: 0.6, blue: 0.8))
            .cropped(to: CGRect(x: 0, y: 0, width: 2, height: 2))
    }
}
