//! Offline comparison of legacy preparation and prepared-JPEG validation/chunking.
//! Usage: <model: mini|link3|square|wide> <quality> <logical.jpg> <printer-oriented.jpg>
//!        <output-directory> [iterations]
//! No scan, connection, Printer command or film consumption occurs.

use std::error::Error;
use std::hint::black_box;
use std::path::PathBuf;
use std::time::Instant;

use instantlink_core::{FitMode, PrinterModel, image};

fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().skip(1).collect();
    if !(5..=6).contains(&args.len()) {
        return Err(
            "expected model quality logical.jpg printer-oriented.jpg output-dir [iterations]"
                .into(),
        );
    }
    let model = match args[0].as_str() {
        "mini" | "0" => PrinterModel::Mini,
        "link3" | "1" => PrinterModel::MiniLink3,
        "square" | "2" => PrinterModel::Square,
        "wide" | "3" => PrinterModel::Wide,
        _ => return Err("unknown model".into()),
    };
    let quality: u8 = args[1].parse()?;
    if !(1..=100).contains(&quality) {
        return Err("quality must be 1..100".into());
    }
    let legacy_input = std::fs::read(&args[2])?;
    let prepared_input = std::fs::read(&args[3])?;
    let output = PathBuf::from(&args[4]);
    let iterations: usize = args.get(5).map_or(Ok(5), |value| value.parse())?;
    if !(1..=1000).contains(&iterations) {
        return Err("iterations must be 1..1000".into());
    }
    image::validate_prepared_jpeg(&prepared_input, model, model, model.spec().flip_vertical)?;
    let mut legacy_ms = Vec::new();
    let mut prepared_ms = Vec::new();
    let mut legacy_output = Vec::new();
    let mut legacy_chunks = 0;
    let mut prepared_chunks = 0;
    for _ in 0..iterations {
        let started = Instant::now();
        let (jpeg, chunks) = image::prepare_image_from_bytes(
            black_box(&legacy_input),
            model,
            FitMode::Stretch,
            quality,
        )?;
        legacy_ms.push(started.elapsed().as_secs_f64() * 1000.0);
        legacy_chunks = black_box(chunks).len();
        legacy_output = jpeg;
        let started = Instant::now();
        image::validate_prepared_jpeg(
            black_box(&prepared_input),
            model,
            model,
            model.spec().flip_vertical,
        )?;
        let chunks = image::chunk_image_data(black_box(&prepared_input), model);
        prepared_ms.push(started.elapsed().as_secs_f64() * 1000.0);
        prepared_chunks = black_box(chunks).len();
    }
    let legacy_rgb = image::load_image_from_bytes(&legacy_output)?.to_rgb8();
    let prepared_rgb = image::load_image_from_bytes(&prepared_input)?.to_rgb8();
    let mut absolute_error = 0.0;
    let mut squared_error = 0.0;
    let mut maximum_error = 0_u8;
    for (legacy, prepared) in legacy_rgb.as_raw().iter().zip(prepared_rgb.as_raw()) {
        let error = legacy.abs_diff(*prepared);
        maximum_error = maximum_error.max(error);
        absolute_error += f64::from(error);
        squared_error += f64::from(error).powi(2);
    }
    let mse = squared_error / legacy_rgb.as_raw().len() as f64;
    let report = serde_json::json!({
        "model": model,
        "quality_supplied_to_legacy": quality,
        "transport_flip_applied": model.spec().flip_vertical,
        "iterations": iterations,
        "architecture": std::env::consts::ARCH,
        "os": std::env::consts::OS,
        "legacy_prepare_ms": legacy_ms,
        "prepared_validate_chunk_ms": prepared_ms,
        "legacy_output_bytes": legacy_output.len(),
        "prepared_output_bytes": prepared_input.len(),
        "legacy_chunks": legacy_chunks,
        "prepared_chunks": prepared_chunks,
        "jpeg_bytes_equal": legacy_output == prepared_input,
        "rgb_mean_absolute_error": absolute_error / legacy_rgb.as_raw().len() as f64,
        "rgb_root_mean_square_error": mse.sqrt(),
        "rgb_maximum_channel_error": maximum_error,
        "rgb_psnr_db": if mse == 0.0 { None } else { Some(10.0 * (255.0_f64.powi(2) / mse).log10()) },
    });
    std::fs::create_dir_all(&output)?;
    std::fs::write(output.join("legacy.jpg"), legacy_output)?;
    std::fs::write(output.join("prepared.jpg"), prepared_input)?;
    let report = serde_json::to_string_pretty(&report)?;
    std::fs::write(output.join("report.json"), &report)?;
    println!("{report}");
    Ok(())
}
