import CoreImage

/// Top-level adjustment composer. PR #1 ships every section as a no-op; each
/// later PR replaces the matching stub with a real filter chain.
struct AdjustmentPipeline {

    func compose(_ source: CIImage, state: EditorSnapshot) -> CIImage {
        var img = source
        // Locked decision Q9 (plan 048 PR #15): when the selected filter is
        // a B&W LUT (mono / noir / silvertone) it overrides the Adjust B&W
        // stack — we skip the desaturate + tone curve + grain chain so the
        // filter has authority and the two passes don't compound.
        let filterIsBW = FilterCatalog.isBlackAndWhite(id: state.filterID)

        img = applyWhiteBalance(img, state.adjustments.whiteBalance)
        img = applyLight(img, state.adjustments.light)
        img = applyCurvesLevels(img, state.adjustments.curves, state.adjustments.levels)
        img = applyColor(img, state.adjustments.color, bwOn: state.adjustments.bw.on)
        img = applySelectiveColor(img, state.adjustments.selective)
        if state.adjustments.bw.on && !filterIsBW {
            img = applyBlackAndWhite(img, state.adjustments.bw)
        }
        img = applyDefinition(img, state.adjustments.definition)
        img = applyNoiseReduction(img, state.adjustments.nr)
        img = applySharpen(img, state.adjustments.sharpen)
        img = applyRedEye(img, state.adjustments.redEye)
        img = applyCrop(img, state.crop)
        img = applyVignette(img, state.adjustments.vignette)
        img = FilterCatalog.apply(img, id: state.filterID)
        return img
    }

    // MARK: - Section stubs (each PR replaces one with its real implementation)

    private func applyWhiteBalance(_ image: CIImage, _ state: AdjustmentState.WhiteBalance) -> CIImage {
        WhiteBalancePipeline.apply(image, state)
    }
    private func applyLight(_ image: CIImage, _ state: AdjustmentState.Light) -> CIImage {
        LightPipeline.apply(image, state)
    }
    private func applyCurvesLevels(_ image: CIImage, _ curves: AdjustmentState.Curves, _ levels: AdjustmentState.Levels) -> CIImage {
        CurvesLevelsPipeline.apply(image, curves: curves, levels: levels)
    }
    private func applyColor(_ image: CIImage, _ state: AdjustmentState.Color, bwOn: Bool) -> CIImage {
        ColorPipeline.apply(image, state, bwOn: bwOn)
    }
    private func applySelectiveColor(_ image: CIImage, _ state: AdjustmentState.SelectiveColor) -> CIImage {
        SelectiveColorKernel.apply(image, state)
    }
    private func applyBlackAndWhite(_ image: CIImage, _ state: AdjustmentState.BlackAndWhite) -> CIImage {
        BlackAndWhitePipeline.apply(image, state)
    }
    private func applyDefinition(_ image: CIImage, _ state: AdjustmentState.Definition) -> CIImage {
        DefinitionPipeline.apply(image, state)
    }
    private func applyNoiseReduction(_ image: CIImage, _ state: AdjustmentState.NoiseReduction) -> CIImage {
        NoiseReductionPipeline.apply(image, state)
    }
    private func applySharpen(_ image: CIImage, _ state: AdjustmentState.Sharpen) -> CIImage {
        SharpenPipeline.apply(image, state)
    }
    private func applyRedEye(_ image: CIImage, _ state: AdjustmentState.RedEye) -> CIImage {
        RedEyePipeline.apply(image, state)
    }
    private func applyCrop(_ image: CIImage, _ state: CropState) -> CIImage { CropPipeline.apply(image, state) }
    private func applyVignette(_ image: CIImage, _ state: AdjustmentState.Vignette) -> CIImage {
        VignettePipeline.apply(image, state)
    }
}
