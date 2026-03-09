//! Printer model definitions and per-model specifications.

use serde::{Deserialize, Serialize};

/// Supported Instax Link printer models.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum PrinterModel {
    /// Instax Mini Link 1/2 (600x800, 900B chunks, 105KB max)
    Mini,
    /// Instax Mini Link 3 (600x800, 900B chunks, 55KB max, vertical flip)
    MiniLink3,
    /// Instax Square Link (800x800, 1808B chunks, 105KB max)
    Square,
    /// Instax Wide Link (1260x840, 900B chunks, 225KB max)
    Wide,
}

/// Per-model specifications.
#[derive(Debug, Clone)]
pub struct ModelSpec {
    /// Image width in pixels.
    pub width: u32,
    /// Image height in pixels.
    pub height: u32,
    /// Data chunk size in bytes for image transfer.
    pub chunk_size: usize,
    /// Human-readable model name.
    pub name: &'static str,
    /// Maximum JPEG image size in bytes.
    pub max_image_size: usize,
    /// Delay in milliseconds between sending data packets. 0 = no delay.
    pub packet_delay_ms: u64,
    /// Delay in milliseconds after DOWNLOAD_END before PRINT_IMAGE. 0 = no delay.
    pub pre_execute_delay_ms: u64,
    /// Model-specific success code returned by PRINT_IMAGE. 0 = standard.
    pub success_code: u8,
    /// Whether the image must be vertically flipped before upload.
    pub flip_vertical: bool,
}

impl PrinterModel {
    /// Get the specification for this printer model.
    pub fn spec(self) -> ModelSpec {
        match self {
            PrinterModel::Mini => ModelSpec {
                width: 600,
                height: 800,
                chunk_size: 900,
                name: "Instax Mini Link",
                max_image_size: 105_000,
                packet_delay_ms: 0,
                pre_execute_delay_ms: 0,
                success_code: 0,
                flip_vertical: false,
            },
            PrinterModel::MiniLink3 => ModelSpec {
                width: 600,
                height: 800,
                chunk_size: 900,
                name: "Instax Mini Link 3",
                max_image_size: 55_000,
                packet_delay_ms: 75,
                pre_execute_delay_ms: 1000,
                success_code: 16,
                flip_vertical: true,
            },
            PrinterModel::Square => ModelSpec {
                width: 800,
                height: 800,
                chunk_size: 1808,
                name: "Instax Square Link",
                max_image_size: 105_000,
                packet_delay_ms: 150,
                pre_execute_delay_ms: 1000,
                success_code: 12,
                flip_vertical: false,
            },
            PrinterModel::Wide => ModelSpec {
                width: 1260,
                height: 840,
                chunk_size: 900,
                name: "Instax Wide Link",
                max_image_size: 225_000,
                packet_delay_ms: 150,
                pre_execute_delay_ms: 0,
                success_code: 15,
                flip_vertical: false,
            },
        }
    }

    /// All supported printer models.
    pub fn all() -> &'static [PrinterModel] {
        &[
            PrinterModel::Mini,
            PrinterModel::MiniLink3,
            PrinterModel::Square,
            PrinterModel::Wide,
        ]
    }
}

impl std::fmt::Display for PrinterModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.spec().name)
    }
}
