//! Exact-output regression and an opt-in, local comparison against the old contain path.

use std::hint::black_box;
use std::io::Cursor;
use std::time::{Duration, Instant};

use image::imageops::FilterType;
use image::{DynamicImage, GenericImageView, ImageBuffer, ImageFormat, Rgb, RgbImage};
use instantlink_core::image::{
    FitMode, chunk_image_data, encode_jpeg, load_image_from_bytes, prepare_image_from_bytes,
    resize_image,
};
use instantlink_core::models::PrinterModel;

// Keep the previous implementation as an independent pixel/output oracle.
fn legacy_contain(img: &DynamicImage, model: PrinterModel) -> DynamicImage {
    let spec = model.spec();
    let resized = img.resize(spec.width, spec.height, FilterType::Lanczos3);
    let (rw, rh) = resized.dimensions();
    let mut canvas = DynamicImage::new_rgb8(spec.width, spec.height);
    if let Some(rgb) = canvas.as_mut_rgb8() {
        for pixel in rgb.pixels_mut() {
            *pixel = Rgb([255, 255, 255]);
        }
    }
    image::imageops::overlay(
        &mut canvas,
        &resized,
        ((spec.width - rw) / 2) as i64,
        ((spec.height - rh) / 2) as i64,
    );
    canvas
}

fn patterned_rgb(width: u32, height: u32) -> DynamicImage {
    DynamicImage::ImageRgb8(RgbImage::from_fn(width, height, |x, y| {
        Rgb([
            (x.wrapping_mul(7).wrapping_add(y * 3) % 256) as u8,
            ((x / 5 + y / 7) % 256) as u8,
            ((x ^ y) % 256) as u8,
        ])
    }))
}

fn assert_same_contain(img: &DynamicImage, model: PrinterModel) {
    let expected = legacy_contain(img, model);
    let actual = resize_image(img, model, FitMode::Contain);
    assert_eq!(actual.dimensions(), expected.dimensions());
    assert_eq!(actual.color(), expected.color());
    assert_eq!(actual.color_space(), expected.color_space());
    assert_eq!(actual.as_bytes(), expected.as_bytes());
}

#[test]
fn contain_rgb_matches_legacy_for_every_model_and_padding_shape() {
    for &model in PrinterModel::all() {
        let spec = model.spec();
        for (width, height) in [
            (spec.width, spec.height),
            (601, 799),
            (799, 601),
            (1, 1),
            (37, 1),
            (1, 37),
            (0, 0),
            (0, 7),
            (7, 0),
        ] {
            assert_same_contain(&patterned_rgb(width, height), model);
        }
    }
}

#[test]
fn contain_does_not_copy_unused_backing_storage_into_padding() {
    // ImageBuffer permits a backing buffer larger than its logical dimensions.
    // Extra storage must never become part of the centered image or white bars.
    let mut pixels = patterned_rgb(600, 400).into_rgb8().into_raw();
    pixels.resize(pixels.len() + 600 * 3 * 5 + 1, 71);
    let img = DynamicImage::ImageRgb8(RgbImage::from_raw(600, 400, pixels).unwrap());
    assert_same_contain(&img, PrinterModel::Mini);
}

#[test]
fn contain_other_pixel_formats_preserve_conversion_and_alpha_blending() {
    let rgb = patterned_rgb(31, 19);
    let rgba = DynamicImage::ImageRgba8(ImageBuffer::from_fn(31, 19, |x, y| {
        image::Rgba([
            (x * 7) as u8,
            (y * 13) as u8,
            ((x + y) * 5) as u8,
            [0, 1, 127, 254, 255][(x as usize + y as usize) % 5],
        ])
    }));
    for img in [
        DynamicImage::ImageLuma8(rgb.to_luma8()),
        DynamicImage::ImageLumaA8(rgba.to_luma_alpha8()),
        rgba.clone(),
        DynamicImage::ImageLuma16(rgb.to_luma16()),
        DynamicImage::ImageLumaA16(rgba.to_luma_alpha16()),
        DynamicImage::ImageRgb16(rgb.to_rgb16()),
        DynamicImage::ImageRgba16(rgba.to_rgba16()),
        DynamicImage::ImageRgb32F(rgb.to_rgb32f()),
        DynamicImage::ImageRgba32F(rgba.to_rgba32f()),
    ] {
        assert_same_contain(&img, PrinterModel::Mini);
    }
}

fn legacy_prepare(data: &[u8], model: PrinterModel, quality: u8) -> (Vec<u8>, Vec<Vec<u8>>) {
    let mut resized = legacy_contain(&load_image_from_bytes(data).unwrap(), model);
    let spec = model.spec();
    if spec.flip_vertical {
        resized = resized.flipv();
    }
    let jpeg = encode_jpeg(&resized, quality, spec.max_image_size).unwrap();
    let chunks = chunk_image_data(&jpeg, model);
    (jpeg, chunks)
}

#[test]
fn contain_preparation_preserves_jpeg_bytes_chunks_and_model_flip() {
    let mut png = Cursor::new(Vec::new());
    patterned_rgb(641, 479)
        .write_to(&mut png, ImageFormat::Png)
        .unwrap();
    for &model in PrinterModel::all() {
        for quality in [1, 97] {
            let expected = legacy_prepare(png.get_ref(), model, quality);
            let actual =
                prepare_image_from_bytes(png.get_ref(), model, FitMode::Contain, quality).unwrap();
            assert_eq!(actual, expected, "{model:?}, quality {quality}");
        }
    }
}

#[test]
fn contain_preparation_preserves_exif_input_behavior() {
    let mut jpeg = encode_jpeg(&patterned_rgb(641, 479), 92, usize::MAX).unwrap();
    // An orientation-6 EXIF tag must retain the loader's existing behavior.
    let exif = b"Exif\0\0II\x2a\0\x08\0\0\0\x01\0\x12\x01\x03\0\x01\0\0\0\x06\0\0\0\0\0\0\0";
    let mut segment = vec![0xff, 0xe1];
    segment.extend_from_slice(&((exif.len() + 2) as u16).to_be_bytes());
    segment.extend_from_slice(exif);
    jpeg.splice(2..2, segment);
    for &model in PrinterModel::all() {
        assert_eq!(
            prepare_image_from_bytes(&jpeg, model, FitMode::Contain, 97).unwrap(),
            legacy_prepare(&jpeg, model, 97),
        );
    }
}

fn elapsed<T>(mut action: impl FnMut() -> T, iterations: usize) -> Duration {
    let start = Instant::now();
    for _ in 0..iterations {
        black_box(action());
    }
    start.elapsed() / iterations as u32
}

fn compare<T>(
    label: &str,
    mut baseline: impl FnMut() -> T,
    mut optimized: impl FnMut() -> T,
    iterations: usize,
) {
    black_box(baseline());
    black_box(optimized());
    let mut before = Vec::new();
    let mut after = Vec::new();
    for sample in 0..9 {
        // Alternate measurement order to reduce thermal/scheduler bias.
        if sample % 2 == 0 {
            before.push(elapsed(&mut baseline, iterations));
            after.push(elapsed(&mut optimized, iterations));
        } else {
            after.push(elapsed(&mut optimized, iterations));
            before.push(elapsed(&mut baseline, iterations));
        }
    }
    before.sort();
    after.sort();
    println!(
        "{label}: legacy={:.3} ms optimized={:.3} ms reduction={:.1}% (median of 9 batches x {iterations})",
        before[4].as_secs_f64() * 1000.0,
        after[4].as_secs_f64() * 1000.0,
        100.0 * (1.0 - after[4].as_secs_f64() / before[4].as_secs_f64()),
    );
    println!(
        "  batch ranges: legacy {:.3}..{:.3} ms, optimized {:.3}..{:.3} ms",
        before[0].as_secs_f64() * 1000.0,
        before[8].as_secs_f64() * 1000.0,
        after[0].as_secs_f64() * 1000.0,
        after[8].as_secs_f64() * 1000.0,
    );
}

/// Run with --release --ignored --nocapture --test-threads=1 on an idle machine.
#[test]
#[ignore = "local wall-clock benchmark; no timing assertions"]
fn benchmark_contain_composition_and_preparation() {
    for (width, height, model) in [
        (600, 800, PrinterModel::Mini),
        (1200, 800, PrinterModel::MiniLink3),
        (4000, 3000, PrinterModel::Wide),
    ] {
        let img = patterned_rgb(width, height);
        assert_same_contain(&img, model);
        compare(
            &format!("contain RGB {width}x{height} {model:?}"),
            || legacy_contain(black_box(&img), model),
            || resize_image(black_box(&img), model, FitMode::Contain),
            10,
        );
        let jpeg_input = encode_jpeg(&img, 92, usize::MAX).unwrap();
        assert_eq!(
            legacy_prepare(&jpeg_input, model, 97),
            prepare_image_from_bytes(&jpeg_input, model, FitMode::Contain, 97).unwrap(),
        );
        compare(
            &format!("full JPEG preparation {width}x{height} {model:?}"),
            || legacy_prepare(black_box(&jpeg_input), model, 97),
            || {
                prepare_image_from_bytes(black_box(&jpeg_input), model, FitMode::Contain, 97)
                    .unwrap()
            },
            5,
        );
    }
}
