//! InstantLink CLI — command-line interface for Instax Link printers.

mod output;

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
use instantlink_core::error::PrinterError;
use instantlink_core::image::FitMode;
use instantlink_core::printer;
use serde::Serialize;

#[derive(Debug, Serialize, PartialEq, Eq)]
struct InfoOutput {
    name: String,
    model: String,
    battery: u8,
    is_charging: bool,
    film_remaining: u8,
    print_count: u16,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct PrintOutput {
    success: bool,
    printer: String,
    model: String,
    image: String,
    fit: String,
    quality: u8,
    color_mode: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct LedSetOutput {
    success: bool,
    printer: String,
    action: &'static str,
    color: String,
    pattern: String,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct LedOffOutput {
    success: bool,
    printer: String,
    action: &'static str,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct StatusOutput {
    connected: bool,
    name: String,
    model: String,
    battery: u8,
    is_charging: bool,
    film_remaining: u8,
    print_count: u16,
}

#[derive(Debug, Serialize, PartialEq, Eq)]
struct DisconnectedStatusOutput {
    connected: bool,
}

fn build_info_output(
    name: &str,
    model: &str,
    battery: u8,
    is_charging: bool,
    film_remaining: u8,
    print_count: u16,
) -> InfoOutput {
    InfoOutput {
        name: name.to_string(),
        model: model.to_string(),
        battery,
        is_charging,
        film_remaining,
        print_count,
    }
}

fn build_print_output(
    printer: &str,
    model: &str,
    image: &Path,
    fit: &str,
    quality: u8,
    color_mode: &str,
) -> PrintOutput {
    PrintOutput {
        success: true,
        printer: printer.to_string(),
        model: model.to_string(),
        image: image.display().to_string(),
        fit: fit.to_string(),
        quality,
        color_mode: color_mode.to_string(),
    }
}

fn build_led_set_output(printer: &str, r: u8, g: u8, b: u8, pattern: &str) -> LedSetOutput {
    LedSetOutput {
        success: true,
        printer: printer.to_string(),
        action: "set",
        color: format!("#{:02x}{:02x}{:02x}", r, g, b),
        pattern: pattern.to_string(),
    }
}

fn build_led_off_output(printer: &str) -> LedOffOutput {
    LedOffOutput {
        success: true,
        printer: printer.to_string(),
        action: "off",
    }
}

fn build_status_output(
    name: &str,
    model: &str,
    battery: u8,
    is_charging: bool,
    film_remaining: u8,
    print_count: u16,
) -> StatusOutput {
    StatusOutput {
        connected: true,
        name: name.to_string(),
        model: model.to_string(),
        battery,
        is_charging,
        film_remaining,
        print_count,
    }
}

fn build_disconnected_status_output() -> DisconnectedStatusOutput {
    DisconnectedStatusOutput { connected: false }
}

fn validate_image_path(path: &Path) -> Result<()> {
    if !path.exists() {
        anyhow::bail!("image file not found: {}", path.display());
    }
    if !path.is_file() {
        anyhow::bail!("image path is not a file: {}", path.display());
    }
    std::fs::File::open(path)
        .with_context(|| format!("image file is not readable: {}", path.display()))?;
    Ok(())
}

fn combine_operation_and_disconnect<T>(
    operation_result: Result<T>,
    disconnect_result: Result<()>,
) -> Result<T> {
    match (operation_result, disconnect_result) {
        (Err(operation_error), _) => Err(operation_error),
        (Ok(_), Err(disconnect_error)) => Err(disconnect_error),
        (Ok(value), Ok(())) => Ok(value),
    }
}

fn status_error_means_disconnected(error: &PrinterError) -> bool {
    matches!(error, PrinterError::PrinterNotFound)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CliFitMode {
    Crop,
    Contain,
    Stretch,
}

impl CliFitMode {
    fn as_str(self) -> &'static str {
        match self {
            CliFitMode::Crop => "crop",
            CliFitMode::Contain => "contain",
            CliFitMode::Stretch => "stretch",
        }
    }

    fn to_core(self) -> FitMode {
        match self {
            CliFitMode::Crop => FitMode::Crop,
            CliFitMode::Contain => FitMode::Contain,
            CliFitMode::Stretch => FitMode::Stretch,
        }
    }
}

fn parse_fit_mode(value: &str) -> std::result::Result<CliFitMode, String> {
    match value.to_ascii_lowercase().as_str() {
        "crop" => Ok(CliFitMode::Crop),
        "contain" => Ok(CliFitMode::Contain),
        "stretch" => Ok(CliFitMode::Stretch),
        _ => Err("expected one of: crop, contain, stretch".to_string()),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ColorMode {
    Rich,
    Natural,
}

impl ColorMode {
    fn as_str(self) -> &'static str {
        match self {
            ColorMode::Rich => "rich",
            ColorMode::Natural => "natural",
        }
    }

    fn label(self) -> &'static str {
        match self {
            ColorMode::Rich => "Rich",
            ColorMode::Natural => "Natural",
        }
    }

    fn print_option(self) -> u8 {
        match self {
            ColorMode::Rich => 0,
            ColorMode::Natural => 1,
        }
    }
}

fn parse_color_mode(value: &str) -> std::result::Result<ColorMode, String> {
    match value.to_ascii_lowercase().as_str() {
        "rich" => Ok(ColorMode::Rich),
        "natural" => Ok(ColorMode::Natural),
        _ => Err("expected one of: rich, natural".to_string()),
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum LedPattern {
    Solid,
    Blink,
    Breathe,
}

impl LedPattern {
    fn as_str(self) -> &'static str {
        match self {
            LedPattern::Solid => "solid",
            LedPattern::Blink => "blink",
            LedPattern::Breathe => "breathe",
        }
    }

    fn byte(self) -> u8 {
        match self {
            LedPattern::Solid => 0,
            LedPattern::Blink => 1,
            LedPattern::Breathe => 2,
        }
    }
}

fn parse_led_pattern(value: &str) -> std::result::Result<LedPattern, String> {
    match value.to_ascii_lowercase().as_str() {
        "solid" => Ok(LedPattern::Solid),
        "blink" => Ok(LedPattern::Blink),
        "breathe" => Ok(LedPattern::Breathe),
        _ => Err("expected one of: solid, blink, breathe".to_string()),
    }
}

#[derive(Debug, Parser)]
#[command(
    name = "instantlink",
    version,
    about = "Print to Fujifilm Instax Link printers"
)]
struct Cli {
    /// Target a specific printer by name.
    #[arg(long, global = true)]
    device: Option<String>,

    /// Output as JSON (for machine consumption).
    #[arg(long, global = true)]
    json: bool,

    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Scan for nearby Instax printers
    Scan {
        /// BLE scan duration in seconds
        #[arg(long, default_value = "5")]
        duration: u64,
    },
    /// Show printer info (battery, film, firmware, print count)
    Info {
        /// BLE scan duration in seconds
        #[arg(long, default_value = "5")]
        duration: u64,
    },
    /// Print an image
    Print {
        /// Path to the image file
        image: PathBuf,
        /// JPEG quality (1-100, default 97)
        #[arg(long, default_value_t = 97, value_parser = clap::value_parser!(u8).range(1..=100))]
        quality: u8,
        /// How to fit the image: crop, contain, or stretch
        #[arg(long, default_value = "crop", value_parser = parse_fit_mode)]
        fit: CliFitMode,
        /// Color mode: rich (vivid) or natural (classic film look)
        #[arg(long, default_value = "rich", value_parser = parse_color_mode)]
        color_mode: ColorMode,
    },
    /// Control the printer LED
    Led {
        #[command(subcommand)]
        action: LedAction,
    },
    /// Show printer status (connectivity + info)
    Status,
}

#[derive(Debug, Subcommand)]
enum LedAction {
    /// Set LED color and pattern
    Set {
        /// Color as hex (#RRGGBB)
        color: String,
        /// Pattern: solid, blink, or breathe
        #[arg(long, default_value = "solid", value_parser = parse_led_pattern)]
        pattern: LedPattern,
    },
    /// Turn LED off
    Off,
}

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::init();
    let cli = Cli::parse();

    match cli.command {
        Commands::Scan { duration } => {
            let sp = output::spinner("Scanning for Instax printers...");
            let printers = printer::scan(Some(Duration::from_secs(duration)))
                .await
                .context("scan failed")?;
            sp.finish_and_clear();

            if cli.json {
                let names: Vec<&str> = printers.iter().map(|p| p.name.as_str()).collect();
                output::print_json(&names)?;
            } else if printers.is_empty() {
                println!("No Instax printers found");
            } else {
                println!("Found {} printer(s):", printers.len());
                for p in &printers {
                    println!("  {}", p.name);
                }
            }
        }

        Commands::Info { duration } => {
            let scan_duration = Some(Duration::from_secs(duration));

            if cli.json {
                eprintln!("progress: Scanning...");
            } else {
                eprint!("Scanning... ");
            }

            let device = match cli.device.as_deref() {
                Some(name) => printer::connect(name, scan_duration).await,
                None => printer::connect_any(scan_duration).await,
            }
            .context("failed to connect to printer")?;

            if cli.json {
                eprintln!("progress: Connected to {}", device.name());
                eprintln!("progress: Detecting model...");
            } else {
                eprint!("connected. ");
            }

            let info_result = async {
                let model = device.model();

                if cli.json {
                    eprintln!("progress: Reading battery...");
                }
                let battery = device.battery().await.context("failed to read battery")?;

                if cli.json {
                    eprintln!("progress: Reading film...");
                }
                let (film_remaining, is_charging) = device
                    .film_and_charging()
                    .await
                    .context("failed to read film")?;

                if cli.json {
                    eprintln!("progress: Reading print count...");
                }
                let print_count = device
                    .print_count()
                    .await
                    .context("failed to read print count")?;

                Ok::<_, anyhow::Error>((model, battery, film_remaining, is_charging, print_count))
            }
            .await;

            let disconnect_result = device.disconnect().await.context("failed to disconnect");
            let (model, battery, film_remaining, is_charging, print_count) = info_result?;
            disconnect_result?;

            if cli.json {
                output::print_json(&build_info_output(
                    device.name(),
                    &model.to_string(),
                    battery,
                    is_charging,
                    film_remaining,
                    print_count,
                ))?;
            } else {
                println!();
                println!("Printer:    {}", device.name());
                println!("Model:      {}", model);
                let charging = if is_charging { " (charging)" } else { "" };
                println!("Battery:    {}%{}", battery, charging);
                println!("Film:       {} remaining", film_remaining);
                println!("Prints:     {}", print_count);
            }
        }

        Commands::Print {
            image,
            quality,
            fit,
            color_mode,
        } => {
            validate_image_path(&image)?;
            let fit_mode = fit.to_core();
            let fit_mode_name = fit.as_str();
            let print_option = color_mode.print_option();

            let sp = (!cli.json).then(|| output::spinner("Connecting to printer..."));
            let device = match cli.device.as_deref() {
                Some(name) => printer::connect(name, None).await?,
                None => printer::connect_any(None).await?,
            };
            if let Some(sp) = sp {
                sp.finish_and_clear();
            }

            let model = device.model();
            let mode_name = color_mode.label();
            if !cli.json {
                println!("Printing to {} ({}) [{}]", device.name(), model, mode_name);
            }
            let transfer_spinner = (!cli.json).then(|| output::spinner("Printing..."));
            let progress = |sent: usize, total: usize| {
                if let Some(sp) = transfer_spinner.as_ref() {
                    sp.set_message(format!("Sending chunk {sent}/{total}..."));
                }
            };

            let print_result = device
                .print_file(
                    &image,
                    fit_mode,
                    quality,
                    print_option,
                    (!cli.json).then_some(&progress),
                )
                .await
                .context("print failed");
            if let Some(sp) = transfer_spinner {
                sp.finish_and_clear();
            }

            let disconnect_result = device.disconnect().await.context("failed to disconnect");
            combine_operation_and_disconnect(print_result, disconnect_result)?;
            if cli.json {
                output::print_json(&build_print_output(
                    device.name(),
                    &model.to_string(),
                    &image,
                    fit_mode_name,
                    quality,
                    color_mode.as_str(),
                ))?;
            } else {
                println!("Print sent to printer");
            }
        }

        Commands::Led { action } => match action {
            LedAction::Set { color, pattern } => {
                let (r, g, b) = parse_hex_color(&color)?;
                let pattern_byte = pattern.byte();

                let device = match cli.device.as_deref() {
                    Some(name) => printer::connect(name, None).await?,
                    None => printer::connect_any(None).await?,
                };

                let result = device
                    .set_led(r, g, b, pattern_byte)
                    .await
                    .context("failed to set LED");
                let disconnect_result = device.disconnect().await.context("failed to disconnect");
                combine_operation_and_disconnect(result, disconnect_result)?;
                if cli.json {
                    output::print_json(&build_led_set_output(
                        device.name(),
                        r,
                        g,
                        b,
                        pattern.as_str(),
                    ))?;
                } else {
                    println!(
                        "LED set to #{:02x}{:02x}{:02x} ({})",
                        r,
                        g,
                        b,
                        pattern.as_str()
                    );
                }
            }
            LedAction::Off => {
                let device = match cli.device.as_deref() {
                    Some(name) => printer::connect(name, None).await?,
                    None => printer::connect_any(None).await?,
                };

                let result = device.led_off().await.context("failed to turn off LED");
                let disconnect_result = device.disconnect().await.context("failed to disconnect");
                combine_operation_and_disconnect(result, disconnect_result)?;
                if cli.json {
                    output::print_json(&build_led_off_output(device.name()))?;
                } else {
                    println!("LED off");
                }
            }
        },

        Commands::Status => {
            let sp = output::spinner("Checking printer status...");
            let status = printer::get_status(cli.device.as_deref(), None).await;
            sp.finish_and_clear();

            match status {
                Ok(status) => {
                    if cli.json {
                        output::print_json(&build_status_output(
                            &status.name,
                            &status.model.to_string(),
                            status.battery,
                            status.is_charging,
                            status.film_remaining,
                            status.print_count,
                        ))?;
                    } else {
                        println!("Connected:  yes");
                        println!("Printer:    {}", status.name);
                        println!("Model:      {}", status.model);
                        let charging = if status.is_charging {
                            " (charging)"
                        } else {
                            ""
                        };
                        println!("Battery:    {}%{}", status.battery, charging);
                        println!("Film:       {} remaining", status.film_remaining);
                        println!("Prints:     {}", status.print_count);
                    }
                }
                Err(err) if status_error_means_disconnected(&err) => {
                    if cli.json {
                        output::print_json(&build_disconnected_status_output())?;
                    } else {
                        println!("Connected:  no");
                        println!("No Instax printer found");
                    }
                }
                Err(err) => return Err(err).context("failed to get printer status"),
            }
        }
    }

    Ok(())
}

/// Parse a hex color string like "#FF0000" or "FF0000" into (r, g, b).
fn parse_hex_color(s: &str) -> Result<(u8, u8, u8)> {
    let hex = s.trim_start_matches('#');
    if hex.len() != 6 {
        anyhow::bail!("invalid hex color: {s} (expected 6 hex digits)");
    }
    let r = u8::from_str_radix(&hex[0..2], 16).context("invalid red component")?;
    let g = u8::from_str_radix(&hex[2..4], 16).context("invalid green component")?;
    let b = u8::from_str_radix(&hex[4..6], 16).context("invalid blue component")?;
    Ok((r, g, b))
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;
    use serde_json::Value;

    fn unique_temp_path(prefix: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!("{prefix}-{}-{nanos}", std::process::id()))
    }

    #[test]
    fn parse_scan_defaults() {
        let cli = Cli::try_parse_from(["instantlink", "scan"]).unwrap();
        match cli.command {
            Commands::Scan { duration } => assert_eq!(duration, 5),
            other => panic!("expected scan command, got {other:?}"),
        }
        assert!(!cli.json);
        assert_eq!(cli.device, None);
    }

    #[test]
    fn parse_print_defaults() {
        let cli = Cli::try_parse_from(["instantlink", "print", "sample.jpg"]).unwrap();
        match cli.command {
            Commands::Print {
                image,
                quality,
                fit,
                color_mode,
            } => {
                assert_eq!(image, PathBuf::from("sample.jpg"));
                assert_eq!(quality, 97);
                assert_eq!(fit, CliFitMode::Crop);
                assert_eq!(color_mode, ColorMode::Rich);
            }
            other => panic!("expected print command, got {other:?}"),
        }
    }

    #[test]
    fn parse_print_custom_values() {
        let cli = Cli::try_parse_from([
            "instantlink",
            "print",
            "nested/photo.jpg",
            "--quality",
            "88",
            "--fit",
            "stretch",
            "--color-mode",
            "natural",
        ])
        .unwrap();
        match cli.command {
            Commands::Print {
                image,
                quality,
                fit,
                color_mode,
            } => {
                assert_eq!(image, PathBuf::from("nested/photo.jpg"));
                assert_eq!(quality, 88);
                assert_eq!(fit, CliFitMode::Stretch);
                assert_eq!(color_mode, ColorMode::Natural);
            }
            other => panic!("expected print command, got {other:?}"),
        }
    }

    #[test]
    fn parse_print_rejects_invalid_fit() {
        let err = Cli::try_parse_from(["instantlink", "print", "sample.jpg", "--fit", "fill"])
            .unwrap_err();
        assert!(err.to_string().contains("crop, contain, stretch"));
    }

    #[test]
    fn parse_print_rejects_invalid_color_mode() {
        let err =
            Cli::try_parse_from(["instantlink", "print", "sample.jpg", "--color-mode", "mono"])
                .unwrap_err();
        assert!(err.to_string().contains("rich, natural"));
    }

    #[test]
    fn parse_print_rejects_quality_outside_declared_range() {
        assert!(
            Cli::try_parse_from(["instantlink", "print", "sample.jpg", "--quality", "0"]).is_err()
        );
        assert!(
            Cli::try_parse_from(["instantlink", "print", "sample.jpg", "--quality", "101"])
                .is_err()
        );
    }

    #[test]
    fn parse_led_set_defaults() {
        let cli = Cli::try_parse_from(["instantlink", "led", "set", "#ff0000"]).unwrap();
        match cli.command {
            Commands::Led { action } => match action {
                LedAction::Set { color, pattern } => {
                    assert_eq!(color, "#ff0000");
                    assert_eq!(pattern, LedPattern::Solid);
                }
                other => panic!("expected led set action, got {other:?}"),
            },
            other => panic!("expected led command, got {other:?}"),
        }
    }

    #[test]
    fn parse_led_rejects_invalid_pattern() {
        let err =
            Cli::try_parse_from(["instantlink", "led", "set", "#ff0000", "--pattern", "pulse"])
                .unwrap_err();
        assert!(err.to_string().contains("solid, blink, breathe"));
    }

    #[test]
    fn parse_global_json_and_device_flags() {
        let cli = Cli::try_parse_from([
            "instantlink",
            "--json",
            "--device",
            "INSTAX-12345678",
            "status",
        ])
        .unwrap();
        assert!(cli.json);
        assert_eq!(cli.device.as_deref(), Some("INSTAX-12345678"));
        assert!(matches!(cli.command, Commands::Status));
    }

    #[test]
    fn validate_image_path_rejects_missing_file() {
        let path = unique_temp_path("instantlink-missing-image");
        let error = validate_image_path(&path).unwrap_err().to_string();
        assert!(error.contains("image file not found"));
    }

    #[test]
    fn validate_image_path_rejects_directory() {
        let error = validate_image_path(&std::env::temp_dir())
            .unwrap_err()
            .to_string();
        assert!(error.contains("image path is not a file"));
    }

    #[test]
    fn validate_image_path_accepts_readable_file() {
        let path = unique_temp_path("instantlink-readable-image");
        std::fs::write(&path, b"placeholder").unwrap();
        let result = validate_image_path(&path);
        std::fs::remove_file(&path).unwrap();
        result.unwrap();
    }

    #[test]
    fn combine_operation_and_disconnect_prefers_operation_error() {
        let result = combine_operation_and_disconnect::<()>(
            Err(anyhow::anyhow!("operation failed")),
            Err(anyhow::anyhow!("disconnect failed")),
        );
        assert_eq!(result.unwrap_err().to_string(), "operation failed");
    }

    #[test]
    fn combine_operation_and_disconnect_returns_disconnect_error_after_success() {
        let result = combine_operation_and_disconnect::<()>(
            Ok(()),
            Err(anyhow::anyhow!("disconnect failed")),
        );
        assert_eq!(result.unwrap_err().to_string(), "disconnect failed");
    }

    #[test]
    fn combine_operation_and_disconnect_returns_operation_value() {
        let result = combine_operation_and_disconnect(Ok(42), Ok(()));
        assert_eq!(result.unwrap(), 42);
    }

    #[test]
    fn status_error_mapping_only_treats_not_found_as_disconnected() {
        assert!(status_error_means_disconnected(
            &PrinterError::PrinterNotFound
        ));
        assert!(!status_error_means_disconnected(
            &PrinterError::MultiplePrinters { count: 2 }
        ));
        assert!(!status_error_means_disconnected(&PrinterError::Timeout));
    }

    #[test]
    fn parse_hex_color_accepts_hash_prefixed_and_plain() {
        assert_eq!(parse_hex_color("#FF0000").unwrap(), (255, 0, 0));
        assert_eq!(parse_hex_color("00ff7f").unwrap(), (0, 255, 127));
    }

    #[test]
    fn parse_hex_color_rejects_invalid_component() {
        let error = parse_hex_color("gg00ff").unwrap_err().to_string();
        assert!(error.contains("invalid red component"));
    }

    #[test]
    fn parse_hex_color_rejects_invalid_length() {
        let error = parse_hex_color("fff").unwrap_err().to_string();
        assert!(error.contains("expected 6 hex digits"));
    }

    #[test]
    fn info_json_emits_expected_payload() {
        let payload = build_info_output("INSTAX-12345678", "Instax Wide Link", 64, true, 5, 91);
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value["name"], "INSTAX-12345678");
        assert_eq!(value["model"], "Instax Wide Link");
        assert_eq!(value["battery"], 64);
        assert_eq!(value["is_charging"], true);
        assert_eq!(value["film_remaining"], 5);
        assert_eq!(value["print_count"], 91);
    }

    #[test]
    fn print_json_emits_expected_payload() {
        let payload = build_print_output(
            "INSTAX-12345678",
            "Instax Mini Link 3",
            &PathBuf::from("photo.jpg"),
            "contain",
            92,
            "natural",
        );
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(value["printer"], "INSTAX-12345678");
        assert_eq!(value["model"], "Instax Mini Link 3");
        assert_eq!(value["image"], "photo.jpg");
        assert_eq!(value["fit"], "contain");
        assert_eq!(value["quality"], 92);
        assert_eq!(value["color_mode"], "natural");
    }

    #[test]
    fn led_set_json_emits_expected_payload() {
        let payload = build_led_set_output("INSTAX-12345678", 255, 153, 49, "blink");
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(value["printer"], "INSTAX-12345678");
        assert_eq!(value["action"], "set");
        assert_eq!(value["color"], "#ff9931");
        assert_eq!(value["pattern"], "blink");
    }

    #[test]
    fn led_off_json_emits_expected_payload() {
        let payload = build_led_off_output("INSTAX-12345678");
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value["success"], true);
        assert_eq!(value["printer"], "INSTAX-12345678");
        assert_eq!(value["action"], "off");
    }

    #[test]
    fn status_json_connected_shape_is_stable() {
        let payload =
            build_status_output("INSTAX-12345678", "Instax Mini Link 3", 82, true, 7, 123);
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value["connected"], true);
        assert_eq!(value["name"], "INSTAX-12345678");
        assert_eq!(value["model"], "Instax Mini Link 3");
        assert_eq!(value["battery"], 82);
        assert_eq!(value["is_charging"], true);
        assert_eq!(value["film_remaining"], 7);
        assert_eq!(value["print_count"], 123);
    }

    #[test]
    fn status_json_disconnected_shape_is_stable() {
        let payload = build_disconnected_status_output();
        let json = output::render_json(&payload).unwrap();
        let value: Value = serde_json::from_str(&json).unwrap();
        assert_eq!(value, serde_json::json!({ "connected": false }));
    }
}
