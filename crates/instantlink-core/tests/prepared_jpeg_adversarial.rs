//! Independent adversarial coverage of the externally prepared JPEG boundary.
use image::codecs::jpeg::JpegEncoder;
use image::{DynamicImage, ExtendedColorType, ImageFormat, Rgb, RgbImage};
use instantlink_core::image::validate_prepared_jpeg;
use instantlink_core::{PrinterError, PrinterModel};
use std::io::Cursor;

fn jpeg(model: PrinterModel) -> Vec<u8> {
    let spec = model.spec();
    let mut data = Vec::new();
    let image = RgbImage::from_fn(spec.width, spec.height, |x, y| {
        if x < spec.width / 3 && y < spec.height / 3 {
            Rgb([210, 40, 70])
        } else {
            Rgb([30, 100, 180])
        }
    });
    JpegEncoder::new_with_quality(&mut data, 80)
        .encode(
            image.as_raw(),
            spec.width,
            spec.height,
            ExtendedColorType::Rgb8,
        )
        .unwrap();
    data
}

fn entropy_start(data: &[u8]) -> usize {
    let start = data
        .windows(2)
        .position(|bytes| bytes == [0xff, 0xda])
        .unwrap();
    start + 2 + u16::from_be_bytes([data[start + 2], data[start + 3]]) as usize
}

fn add_padding(mut data: Vec<u8>, size: usize) -> Vec<u8> {
    let mut padding = size - data.len();
    while padding > 0 {
        let length = padding.min(65_537);
        assert!(length >= 4);
        let mut segment = vec![0; length];
        segment[..2].copy_from_slice(&[0xff, 0xef]);
        segment[2..4].copy_from_slice(&((length - 2) as u16).to_be_bytes());
        data.splice(2..2, segment);
        padding -= length;
    }
    data
}

#[test]
fn all_models_accept_rgb_without_mutating_encoded_payload() {
    for &model in PrinterModel::all() {
        let original = jpeg(model);
        let data = original.clone();
        validate_prepared_jpeg(&data, model, model, model.spec().flip_vertical).unwrap();
        assert_eq!(data, original);
    }
}

#[test]
fn mini_and_link3_equal_dimensions_do_not_bypass_exact_identity_or_flip_guard() {
    let data = jpeg(PrinterModel::Mini);
    for (expected, detected) in [
        (PrinterModel::Mini, PrinterModel::MiniLink3),
        (PrinterModel::MiniLink3, PrinterModel::Mini),
    ] {
        assert!(
            validate_prepared_jpeg(&data, expected, detected, detected.spec().flip_vertical)
                .is_err()
        );
    }
    assert!(validate_prepared_jpeg(&data, PrinterModel::Mini, PrinterModel::Mini, true).is_err());
    assert!(
        validate_prepared_jpeg(
            &data,
            PrinterModel::MiniLink3,
            PrinterModel::MiniLink3,
            false
        )
        .is_err()
    );
}

#[test]
fn rgb_sized_grayscale_cmyk_and_png_are_rejected() {
    let model = PrinterModel::Mini;
    let spec = model.spec();
    let mut gray = Vec::new();
    JpegEncoder::new_with_quality(&mut gray, 80)
        .encode(
            &vec![90; (spec.width * spec.height) as usize],
            spec.width,
            spec.height,
            ExtendedColorType::L8,
        )
        .unwrap();
    let mut png = Cursor::new(Vec::new());
    DynamicImage::new_rgb8(spec.width, spec.height)
        .write_to(&mut png, ImageFormat::Png)
        .unwrap();
    for data in [
        gray.as_slice(),
        include_bytes!("fixtures/cmyk-mini.jpg").as_slice(),
        png.get_ref().as_slice(),
    ] {
        assert!(validate_prepared_jpeg(data, model, model, false).is_err());
    }
}

#[test]
fn truncated_entropy_is_rejected_even_with_restored_eoi() {
    let model = PrinterModel::Mini;
    let data = jpeg(model);
    let start = entropy_start(&data);
    let entropy_length = data.len() - start - 2;
    for kept in [
        entropy_length / 4,
        entropy_length / 2,
        entropy_length * 3 / 4,
    ] {
        let mut truncated = data[..start + kept].to_vec();
        truncated.extend_from_slice(&[0xff, 0xd9]);
        assert!(
            validate_prepared_jpeg(&truncated, model, model, false).is_err(),
            "truncated entropy with restored EOI accepted after {kept} bytes"
        );
    }
    for end in [0, 1, start, data.len() - 1, data.len() - 2] {
        assert!(validate_prepared_jpeg(&data[..end], model, model, false).is_err());
    }
}

#[test]
fn concatenated_jpegs_or_any_trailing_data_are_rejected() {
    let model = PrinterModel::Mini;
    let original = jpeg(model);
    for suffix in [vec![0], vec![0xff], vec![0xff, 0xd9], original.clone()] {
        let mut data = original.clone();
        data.extend_from_slice(&suffix);
        assert!(validate_prepared_jpeg(&data, model, model, false).is_err());
    }
}

#[test]
fn model_byte_limit_is_inclusive_and_oversize_cannot_hide_in_jpeg_metadata() {
    for &model in PrinterModel::all() {
        let limit = model.spec().max_image_size;
        let exact = add_padding(jpeg(model), limit);
        assert_eq!(exact.len(), limit);
        validate_prepared_jpeg(&exact, model, model, model.spec().flip_vertical).unwrap();
        let oversized = add_padding(jpeg(model), limit + 1);
        assert!(matches!(
            validate_prepared_jpeg(&oversized, model, model, model.spec().flip_vertical),
            Err(PrinterError::ImageTooLarge { size, max }) if size == limit + 1 && max == limit
        ));
    }
}

fn with_orientation(mut data: Vec<u8>, orientation: u16) -> Vec<u8> {
    let mut exif = b"Exif\0\0II\x2a\0\x08\0\0\0\x01\0\x12\x01\x03\0\x01\0\0\0".to_vec();
    exif.extend_from_slice(&orientation.to_le_bytes());
    exif.extend_from_slice(&[0, 0, 0, 0, 0, 0]);
    let mut segment = vec![0xff, 0xe1];
    segment.extend_from_slice(&((exif.len() + 2) as u16).to_be_bytes());
    segment.extend(exif);
    data.splice(2..2, segment);
    data
}

#[test]
fn progressive_rgb_jpeg_is_rejected_until_printer_support_is_verified() {
    let data = include_bytes!("fixtures/progressive-mini.jpg");
    assert!(validate_prepared_jpeg(data, PrinterModel::Mini, PrinterModel::Mini, false).is_err());
}

#[test]
fn non_neutral_exif_orientation_cannot_change_prepared_pixel_orientation() {
    let model = PrinterModel::Mini;
    let base = jpeg(model);
    validate_prepared_jpeg(&with_orientation(base.clone(), 1), model, model, false).unwrap();
    for orientation in 2..=8 {
        assert!(
            validate_prepared_jpeg(
                &with_orientation(base.clone(), orientation),
                model,
                model,
                false
            )
            .is_err()
        );
    }
}

#[test]
fn duplicate_exif_segments_do_not_hide_non_neutral_orientation() {
    let model = PrinterModel::Mini;
    for (first, second) in [(1, 6), (6, 1)] {
        let data = with_orientation(with_orientation(jpeg(model), first), second);
        assert!(validate_prepared_jpeg(&data, model, model, false).is_err());
    }
}
