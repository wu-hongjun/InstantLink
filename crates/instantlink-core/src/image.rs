//! Image loading, resizing, JPEG encoding, and chunking for Instax printers.

use std::io::Cursor;
use std::path::Path;

use image::imageops::FilterType;
use image::metadata::Orientation;
use image::{DynamicImage, GenericImageView};

use crate::error::{PrinterError, Result};
use crate::models::PrinterModel;

/// How to fit the image to the printer's aspect ratio.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FitMode {
    /// Crop to fill (default) — may cut edges.
    Crop,
    /// Contain within bounds — may add white bars.
    Contain,
    /// Stretch to exact dimensions — may distort.
    Stretch,
}

impl FitMode {
    /// Parse from string, case-insensitive.
    pub fn from_str_lossy(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "contain" => FitMode::Contain,
            "stretch" => FitMode::Stretch,
            _ => FitMode::Crop,
        }
    }
}

/// Load an image from a file path.
pub fn load_image(path: &Path) -> Result<DynamicImage> {
    image::open(path).map_err(|e| PrinterError::Image(format!("failed to load image: {e}")))
}

/// Resize and fit the image to the printer's dimensions.
pub fn resize_image(img: &DynamicImage, model: PrinterModel, fit: FitMode) -> DynamicImage {
    let spec = model.spec();
    let target_w = spec.width;
    let target_h = spec.height;

    match fit {
        FitMode::Crop => img.resize_to_fill(target_w, target_h, FilterType::Lanczos3),
        FitMode::Contain => {
            let resized = img.resize(target_w, target_h, FilterType::Lanczos3);
            let (rw, rh) = resized.dimensions();
            let mut canvas = DynamicImage::new_rgb8(target_w, target_h);
            // Fill with white
            if let Some(rgb) = canvas.as_mut_rgb8() {
                for pixel in rgb.pixels_mut() {
                    *pixel = image::Rgb([255, 255, 255]);
                }
            }
            image::imageops::overlay(
                &mut canvas,
                &resized,
                ((target_w - rw) / 2) as i64,
                ((target_h - rh) / 2) as i64,
            );
            canvas
        }
        FitMode::Stretch => img.resize_exact(target_w, target_h, FilterType::Lanczos3),
    }
}

/// Encode an image as JPEG, finding the highest quality that fits within `max_size`.
///
/// Uses binary search to maximize quality while staying under the limit.
pub fn encode_jpeg(img: &DynamicImage, initial_quality: u8, max_size: usize) -> Result<Vec<u8>> {
    let rgb = img.to_rgb8();

    let encode_at = |q: u8| -> std::result::Result<Vec<u8>, PrinterError> {
        let mut buf = Cursor::new(Vec::new());
        let encoder = image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, q);
        rgb.write_with_encoder(encoder)
            .map_err(|e| PrinterError::Image(format!("JPEG encode failed: {e}")))?;
        Ok(buf.into_inner())
    };

    // Try the requested quality first — often fits for smaller images.
    let capped = initial_quality.min(100);
    let data = encode_at(capped)?;
    if data.len() <= max_size {
        log::debug!("JPEG encoded: {} bytes at quality {}", data.len(), capped);
        return Ok(data);
    }

    // Binary search for the highest quality that fits.
    let mut low: u8 = 1;
    let mut high: u8 = capped.saturating_sub(1);
    let mut best_data: Option<Vec<u8>> = None;
    let mut best_quality: u8 = 0;
    let mut min_quality_size: Option<usize> = None;

    while low <= high {
        let mid = low + (high - low) / 2;
        let attempt = encode_at(mid)?;
        if min_quality_size.is_none() || mid <= low {
            min_quality_size = Some(attempt.len());
        }
        if attempt.len() <= max_size {
            best_quality = mid;
            best_data = Some(attempt);
            low = mid + 1;
        } else {
            if mid == 0 {
                break;
            }
            high = mid - 1;
        }
    }

    match best_data {
        Some(data) => {
            log::debug!(
                "JPEG encoded: {} bytes at quality {} (reduced from {})",
                data.len(),
                best_quality,
                capped
            );
            Ok(data)
        }
        None => {
            let size = min_quality_size.unwrap_or_else(|| encode_at(1).map_or(0, |d| d.len()));
            Err(PrinterError::ImageTooLarge {
                size,
                max: max_size,
            })
        }
    }
}

/// Split JPEG data into chunks appropriate for the printer model.
///
/// The last chunk is zero-padded to the full chunk size, matching the
/// reference implementation's behavior.
pub fn chunk_image_data(data: &[u8], model: PrinterModel) -> Vec<Vec<u8>> {
    let chunk_size = model.spec().chunk_size;
    let mut chunks: Vec<Vec<u8>> = data.chunks(chunk_size).map(|c| c.to_vec()).collect();
    // Pad last chunk to full chunk_size with zeros
    if let Some(last) = chunks.last_mut()
        && last.len() < chunk_size
    {
        last.resize(chunk_size, 0);
    }
    chunks
}

/// Validate a complete, printer-oriented JPEG without changing its encoded bytes.
///
/// The caller supplies exact model identity and declares whether the model's
/// transport flip was applied before encoding. Only 8-bit, three-component
/// baseline JPEGs with exact print dimensions and no trailing data
/// are accepted. A strict full entropy decode catches corrupt/truncated scans;
/// pixel allocation is bounded by the model dimensions checked beforehand.
/// Raw pixels are authoritative: recognized non-neutral EXIF orientation is
/// rejected; no metadata transform is applied on this path.
pub fn validate_prepared_jpeg(
    data: &[u8],
    expected_model: PrinterModel,
    detected_model: PrinterModel,
    transport_flip_applied: bool,
) -> Result<()> {
    if expected_model != detected_model {
        return Err(PrinterError::Image("prepared JPEG model mismatch".into()));
    }
    let spec = detected_model.spec();
    if transport_flip_applied != spec.flip_vertical {
        return Err(PrinterError::Image(
            "prepared JPEG transport flip mismatch".into(),
        ));
    }
    if data.len() > spec.max_image_size {
        return Err(PrinterError::ImageTooLarge {
            size: data.len(),
            max: spec.max_image_size,
        });
    }
    validate_jpeg_structure(data, spec.width, spec.height)?;
    validate_jpeg_entropy(data, spec.width, spec.height)
}

/// A private per-call handle; no global decoder state or callbacks cross this boundary.
struct StrictJpegDecoder(std::ptr::NonNull<std::ffi::c_void>);

impl StrictJpegDecoder {
    fn parameter(&self, parameter: turbojpeg_sys::TJPARAM) -> i32 {
        // SAFETY: reads one documented parameter of this private live handle.
        unsafe { turbojpeg_sys::tj3Get(self.0.as_ptr(), parameter as i32) }
    }
    fn error(&self) -> PrinterError {
        // SAFETY: this handle remains live until Drop; TurboJPEG owns its
        // null-terminated error string, which is copied before another call.
        let message = unsafe {
            let pointer = turbojpeg_sys::tj3GetErrorStr(self.0.as_ptr());
            if pointer.is_null() {
                "unknown JPEG validation error".into()
            } else {
                std::ffi::CStr::from_ptr(pointer)
                    .to_string_lossy()
                    .into_owned()
            }
        };
        PrinterError::Image(format!("invalid prepared JPEG: {message}"))
    }
}

impl Drop for StrictJpegDecoder {
    fn drop(&mut self) {
        // SAFETY: this owns one successful tj3Init handle and destroys it once.
        unsafe { turbojpeg_sys::tj3Destroy(self.0.as_ptr()) };
    }
}

fn validate_jpeg_entropy(data: &[u8], width: u32, height: u32) -> Result<()> {
    // SAFETY: initialization takes no pointers and creates an owned handle.
    let pointer = unsafe { turbojpeg_sys::tj3Init(turbojpeg_sys::TJINIT_TJINIT_DECOMPRESS as i32) };
    let decoder = StrictJpegDecoder(std::ptr::NonNull::new(pointer).ok_or_else(|| {
        PrinterError::Image("could not initialize prepared JPEG validator".into())
    })?);
    // A warning such as premature EOI must be a validation error, never a
    // successful decode with missing MCUs filled in. Other Rust JPEG decoders
    // recover this case even with their strict setting enabled.
    // SAFETY: live private handle; STOPONWARNING accepts integer 0 or 1.
    if unsafe {
        turbojpeg_sys::tj3Set(
            decoder.0.as_ptr(),
            turbojpeg_sys::TJPARAM_TJPARAM_STOPONWARNING as i32,
            1,
        )
    } != 0
    {
        return Err(decoder.error());
    }
    // SAFETY: header inspection reads the bounded immutable slice. It does not
    // write pixels and uses the same private STOPONWARNING-enabled handle.
    if unsafe {
        turbojpeg_sys::tj3DecompressHeader(
            decoder.0.as_ptr(),
            data.as_ptr(),
            data.len() as turbojpeg_sys::size_t,
        )
    } != 0
    {
        return Err(decoder.error());
    }
    let colorspace = decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_COLORSPACE);
    if decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_JPEGWIDTH) != width as i32
        || decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_JPEGHEIGHT) != height as i32
        || decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_PRECISION) != 8
        || decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_PROGRESSIVE) != 0
        || decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_LOSSLESS) != 0
        || decoder.parameter(turbojpeg_sys::TJPARAM_TJPARAM_ARITHMETIC) != 0
        || ![
            turbojpeg_sys::TJCS_TJCS_RGB as i32,
            turbojpeg_sys::TJCS_TJCS_YCbCr as i32,
        ]
        .contains(&colorspace)
    {
        return Err(invalid_prepared_jpeg());
    }
    let mut pixels = vec![0_u8; width as usize * height as usize * 3];
    // SAFETY: the bounded structural check verified these exact dimensions
    // before allocation; data is valid for this call, pixels is an RGB buffer
    // of height * pitch bytes, and the private handle cannot be used concurrently.
    if unsafe {
        turbojpeg_sys::tj3Decompress8(
            decoder.0.as_ptr(),
            data.as_ptr(),
            data.len() as turbojpeg_sys::size_t,
            pixels.as_mut_ptr(),
            (width * 3) as i32,
            turbojpeg_sys::TJPF_TJPF_RGB,
        )
    } != 0
    {
        return Err(decoder.error());
    }
    Ok(())
}

fn invalid_prepared_jpeg() -> PrinterError {
    PrinterError::Image("invalid prepared RGB JPEG structure or dimensions".into())
}

fn validate_jpeg_structure(data: &[u8], width: u32, height: u32) -> Result<()> {
    if !data.starts_with(&[0xff, 0xd8]) {
        return Err(invalid_prepared_jpeg());
    }
    let mut position = 2;
    let mut in_scan = false;
    let mut saw_frame = false;
    let mut saw_scan = false;
    while position < data.len() {
        if in_scan {
            while position < data.len() && data[position] != 0xff {
                position += 1;
            }
        }
        if data.get(position) != Some(&0xff) {
            return Err(invalid_prepared_jpeg());
        }
        while data.get(position) == Some(&0xff) {
            position += 1;
        }
        let marker = *data.get(position).ok_or_else(invalid_prepared_jpeg)?;
        position += 1;
        if in_scan && (marker == 0x00 || (0xd0..=0xd7).contains(&marker)) {
            continue;
        }
        in_scan = false;
        if marker == 0xd9 {
            return if saw_frame && saw_scan && position == data.len() {
                Ok(())
            } else {
                Err(invalid_prepared_jpeg())
            };
        }
        // DNL/hierarchical/arithmetic/reserved frame extensions cannot change
        // dimensions or coding mode after the checked baseline frame header.
        if matches!(
            marker,
            0x00 | 0x01 | 0xc8 | 0xcc | 0xd0..=0xd8 | 0xdc | 0xde | 0xdf
        ) {
            return Err(invalid_prepared_jpeg());
        }
        let length_bytes = data
            .get(position..position + 2)
            .ok_or_else(invalid_prepared_jpeg)?;
        let length = u16::from_be_bytes([length_bytes[0], length_bytes[1]]) as usize;
        if length < 2 {
            return Err(invalid_prepared_jpeg());
        }
        let segment = data
            .get(position + 2..position + length)
            .ok_or_else(invalid_prepared_jpeg)?;
        if marker == 0xe1
            && let Some(exif) = segment.strip_prefix(b"Exif\0\0")
            && Orientation::from_exif_chunk(exif)
                .is_some_and(|orientation| orientation != Orientation::NoTransforms)
        {
            return Err(PrinterError::Image(
                "prepared JPEG contains non-neutral EXIF orientation".into(),
            ));
        }
        if marker == 0xc0 {
            if saw_frame
                || segment.len() != 15
                || segment[0] != 8
                || segment[5] != 3
                || u16::from_be_bytes([segment[1], segment[2]]) as u32 != height
                || u16::from_be_bytes([segment[3], segment[4]]) as u32 != width
            {
                return Err(invalid_prepared_jpeg());
            }
            saw_frame = true;
        } else if matches!(marker, 0xc1..=0xc3 | 0xc5..=0xc7 | 0xc9..=0xcb | 0xcd..=0xcf) {
            return Err(invalid_prepared_jpeg());
        } else if marker == 0xda {
            if !saw_frame
                || segment.is_empty()
                || !(1..=3).contains(&segment[0])
                || segment.len() != 4 + 2 * segment[0] as usize
            {
                return Err(invalid_prepared_jpeg());
            }
            saw_scan = true;
            in_scan = true;
        }
        position += length;
    }
    Err(invalid_prepared_jpeg())
}

/// Shared image preparation pipeline: resize → flip (if needed) → encode → chunk.
fn prepare_image_inner(
    img: DynamicImage,
    model: PrinterModel,
    fit: FitMode,
    quality: u8,
) -> Result<(Vec<u8>, Vec<Vec<u8>>)> {
    let spec = model.spec();
    let mut resized = resize_image(&img, model, fit);
    if spec.flip_vertical {
        resized = resized.flipv();
    }
    let jpeg_data = encode_jpeg(&resized, quality, spec.max_image_size)?;
    let chunks = chunk_image_data(&jpeg_data, model);
    Ok((jpeg_data, chunks))
}

/// Complete image preparation pipeline: load → resize → flip (if needed) → encode → chunk.
pub fn prepare_image(
    path: &Path,
    model: PrinterModel,
    fit: FitMode,
    quality: u8,
) -> Result<(Vec<u8>, Vec<Vec<u8>>)> {
    prepare_image_inner(load_image(path)?, model, fit, quality)
}

/// Load an image from raw bytes (for use from FFI or other non-file sources).
pub fn load_image_from_bytes(data: &[u8]) -> Result<DynamicImage> {
    image::load_from_memory(data)
        .map_err(|e| PrinterError::Image(format!("failed to load image from bytes: {e}")))
}

/// Prepare an image from raw bytes (skip file loading).
pub fn prepare_image_from_bytes(
    data: &[u8],
    model: PrinterModel,
    fit: FitMode,
    quality: u8,
) -> Result<(Vec<u8>, Vec<Vec<u8>>)> {
    prepare_image_inner(load_image_from_bytes(data)?, model, fit, quality)
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::ImageFormat;
    use image::RgbImage;

    fn create_test_image(w: u32, h: u32) -> DynamicImage {
        DynamicImage::new_rgb8(w, h)
    }

    #[test]
    fn fit_mode_from_str() {
        assert_eq!(FitMode::from_str_lossy("crop"), FitMode::Crop);
        assert_eq!(FitMode::from_str_lossy("Contain"), FitMode::Contain);
        assert_eq!(FitMode::from_str_lossy("STRETCH"), FitMode::Stretch);
        assert_eq!(FitMode::from_str_lossy("unknown"), FitMode::Crop);
    }

    #[test]
    fn resize_crop_dimensions() {
        let img = create_test_image(1000, 1000);
        let resized = resize_image(&img, PrinterModel::Mini, FitMode::Crop);
        let (w, h) = resized.dimensions();
        assert_eq!(w, 600);
        assert_eq!(h, 800);
    }

    #[test]
    fn resize_contain_dimensions() {
        let img = create_test_image(1000, 1000);
        let resized = resize_image(&img, PrinterModel::Mini, FitMode::Contain);
        let (w, h) = resized.dimensions();
        assert_eq!(w, 600);
        assert_eq!(h, 800);
    }

    #[test]
    fn resize_stretch_dimensions() {
        let img = create_test_image(1000, 500);
        let resized = resize_image(&img, PrinterModel::Square, FitMode::Stretch);
        let (w, h) = resized.dimensions();
        assert_eq!(w, 800);
        assert_eq!(h, 800);
    }

    #[test]
    fn resize_wide_model() {
        let img = create_test_image(2000, 1000);
        let resized = resize_image(&img, PrinterModel::Wide, FitMode::Crop);
        let (w, h) = resized.dimensions();
        assert_eq!(w, 1260);
        assert_eq!(h, 840);
    }

    #[test]
    fn encode_jpeg_produces_data() {
        let img = create_test_image(600, 800);
        let max_size = PrinterModel::Mini.spec().max_image_size;
        let data = encode_jpeg(&img, 97, max_size).unwrap();
        assert!(!data.is_empty());
        // JPEG magic bytes
        assert_eq!(data[0], 0xFF);
        assert_eq!(data[1], 0xD8);
    }

    #[test]
    fn encode_jpeg_fits_within_max() {
        let img = create_test_image(600, 800);
        let max_size = PrinterModel::Mini.spec().max_image_size;
        let data = encode_jpeg(&img, 97, max_size).unwrap();
        assert!(data.len() <= max_size);
    }

    #[test]
    fn encode_jpeg_link3_size_limit() {
        let img = create_test_image(600, 800);
        let max_size = PrinterModel::MiniLink3.spec().max_image_size;
        let data = encode_jpeg(&img, 97, max_size).unwrap();
        assert!(data.len() <= max_size);
    }

    #[test]
    fn chunk_image_data_mini() {
        let data = vec![0u8; 5000];
        let chunks = chunk_image_data(&data, PrinterModel::Mini);
        // 5000 / 900 = 5.55 → 6 chunks
        assert_eq!(chunks.len(), 6);
        assert_eq!(chunks[0].len(), 900);
        // Last chunk is padded to full chunk size
        assert_eq!(chunks[5].len(), 900);
    }

    #[test]
    fn chunk_image_data_square() {
        let data = vec![0u8; 5000];
        let chunks = chunk_image_data(&data, PrinterModel::Square);
        // 5000 / 1808 = 2.76 → 3 chunks
        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].len(), 1808);
        // Last chunk is padded to full chunk size
        assert_eq!(chunks[2].len(), 1808);
    }

    #[test]
    fn chunk_image_data_empty() {
        let data: Vec<u8> = vec![];
        let chunks = chunk_image_data(&data, PrinterModel::Mini);
        assert!(chunks.is_empty());
    }

    #[test]
    fn load_from_bytes_png() {
        // Create a minimal valid PNG in memory
        let img = create_test_image(10, 10);
        let mut buf = Cursor::new(Vec::new());
        img.write_to(&mut buf, ImageFormat::Png).unwrap();
        let loaded = load_image_from_bytes(&buf.into_inner()).unwrap();
        let (w, h) = loaded.dimensions();
        assert_eq!(w, 10);
        assert_eq!(h, 10);
    }

    #[test]
    fn load_from_bytes_invalid() {
        let result = load_image_from_bytes(&[0, 1, 2, 3]);
        assert!(result.is_err());
    }

    #[test]
    fn model_specs_correct() {
        // Verify all 4 model specs
        let mini = PrinterModel::Mini.spec();
        assert_eq!(mini.max_image_size, 105_000);
        assert_eq!(mini.packet_delay_ms, 0);
        assert_eq!(mini.success_code, 0);
        assert!(!mini.flip_vertical);

        let link3 = PrinterModel::MiniLink3.spec();
        assert_eq!(link3.max_image_size, 55_000);
        assert_eq!(link3.packet_delay_ms, 75);
        assert_eq!(link3.success_code, 16);
        assert!(link3.flip_vertical);

        let square = PrinterModel::Square.spec();
        assert_eq!(square.max_image_size, 105_000);
        assert_eq!(square.success_code, 12);

        let wide = PrinterModel::Wide.spec();
        assert_eq!(wide.max_image_size, 225_000);
        assert_eq!(wide.success_code, 15);
    }

    #[test]
    fn all_models_includes_link3() {
        let all = PrinterModel::all();
        assert_eq!(all.len(), 4);
        assert!(all.contains(&PrinterModel::MiniLink3));
    }

    #[test]
    fn encode_jpeg_returns_image_too_large_when_quality_one_still_exceeds_limit() {
        let img = create_test_image(600, 800);
        let err = encode_jpeg(&img, 1, 1).unwrap_err();
        match err {
            PrinterError::ImageTooLarge { size, max } => {
                assert!(size > max);
                assert_eq!(max, 1);
            }
            other => panic!("expected ImageTooLarge, got {other:?}"),
        }
    }

    #[test]
    fn prepare_image_from_bytes_flips_vertically_for_link3() {
        let width = PrinterModel::MiniLink3.spec().width;
        let height = PrinterModel::MiniLink3.spec().height;
        let mut rgb = RgbImage::new(width, height);
        for y in 0..height {
            for x in 0..width {
                let pixel = if y < height / 2 {
                    image::Rgb([255, 0, 0])
                } else {
                    image::Rgb([0, 0, 255])
                };
                rgb.put_pixel(x, y, pixel);
            }
        }

        let mut encoded = Cursor::new(Vec::new());
        DynamicImage::ImageRgb8(rgb)
            .write_to(&mut encoded, ImageFormat::Png)
            .unwrap();

        let (jpeg, _) = prepare_image_from_bytes(
            &encoded.into_inner(),
            PrinterModel::MiniLink3,
            FitMode::Crop,
            97,
        )
        .unwrap();
        let processed = load_image_from_bytes(&jpeg).unwrap().to_rgb8();
        let top = processed.get_pixel(width / 2, height / 4);
        let bottom = processed.get_pixel(width / 2, (height * 3) / 4);

        assert!(
            top[2] > top[0],
            "expected blue-dominant top pixel, got {top:?}"
        );
        assert!(
            bottom[0] > bottom[2],
            "expected red-dominant bottom pixel, got {bottom:?}"
        );
    }
}
