//! InstantLink CLI — command-line interface for Instax Link printers.

mod output;

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result};
use clap::{Parser, Subcommand};
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
        #[arg(long, default_value = "97")]
        quality: u8,
        /// How to fit the image: crop, contain, or stretch
        #[arg(long, default_value = "crop")]
        fit: String,
        /// Color mode: rich (vivid) or natural (classic film look)
        #[arg(long, default_value = "rich")]
        color_mode: String,
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
        #[arg(long, default_value = "solid")]
        pattern: String,
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
            let fit_mode = FitMode::from_str_lossy(&fit);
            let fit_mode_name = match fit_mode {
                FitMode::Crop => "crop",
                FitMode::Contain => "contain",
                FitMode::Stretch => "stretch",
            };
            let print_option: u8 = match color_mode.to_lowercase().as_str() {
                "natural" => 1,
                _ => 0, // rich (default)
            };

            let sp = (!cli.json).then(|| output::spinner("Connecting to printer..."));
            let device = match cli.device.as_deref() {
                Some(name) => printer::connect(name, None).await?,
                None => printer::connect_any(None).await?,
            };
            if let Some(sp) = sp {
                sp.finish_and_clear();
            }

            let model = device.model();
            let mode_name = if print_option == 0 { "Rich" } else { "Natural" };
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
                .await;
            if let Some(sp) = transfer_spinner {
                sp.finish_and_clear();
            }

            device.disconnect().await?;
            print_result.context("print failed")?;
            if cli.json {
                output::print_json(&build_print_output(
                    device.name(),
                    &model.to_string(),
                    &image,
                    fit_mode_name,
                    quality,
                    &mode_name.to_ascii_lowercase(),
                ))?;
            } else {
                println!("Print complete!");
            }
        }

        Commands::Led { action } => match action {
            LedAction::Set { color, pattern } => {
                let (r, g, b) = parse_hex_color(&color)?;
                let pattern_byte = match pattern.to_lowercase().as_str() {
                    "blink" => 1,
                    "breathe" => 2,
                    _ => 0, // solid
                };

                let device = match cli.device.as_deref() {
                    Some(name) => printer::connect(name, None).await?,
                    None => printer::connect_any(None).await?,
                };

                let result = device.set_led(r, g, b, pattern_byte).await;
                device.disconnect().await?;
                result.context("failed to set LED")?;
                if cli.json {
                    output::print_json(&build_led_set_output(device.name(), r, g, b, &pattern))?;
                } else {
                    println!("LED set to #{:02x}{:02x}{:02x} ({})", r, g, b, pattern);
                }
            }
            LedAction::Off => {
                let device = match cli.device.as_deref() {
                    Some(name) => printer::connect(name, None).await?,
                    None => printer::connect_any(None).await?,
                };

                let result = device.led_off().await;
                device.disconnect().await?;
                result.context("failed to turn off LED")?;
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
                Err(_) => {
                    if cli.json {
                        output::print_json(&build_disconnected_status_output())?;
                    } else {
                        println!("Connected:  no");
                        println!("No Instax printer found");
                    }
                }
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
                assert_eq!(fit, "crop");
                assert_eq!(color_mode, "rich");
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
                assert_eq!(fit, "stretch");
                assert_eq!(color_mode, "natural");
            }
            other => panic!("expected print command, got {other:?}"),
        }
    }

    #[test]
    fn parse_led_set_defaults() {
        let cli = Cli::try_parse_from(["instantlink", "led", "set", "#ff0000"]).unwrap();
        match cli.command {
            Commands::Led { action } => match action {
                LedAction::Set { color, pattern } => {
                    assert_eq!(color, "#ff0000");
                    assert_eq!(pattern, "solid");
                }
                other => panic!("expected led set action, got {other:?}"),
            },
            other => panic!("expected led command, got {other:?}"),
        }
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
