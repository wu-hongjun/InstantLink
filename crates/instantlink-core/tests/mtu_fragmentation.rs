//! Independent checks of fragmentation, exact print payloads, and failure ordering.
use std::num::NonZeroUsize;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;
use tokio::sync::Notify;

use async_trait::async_trait;
use image::codecs::jpeg::JpegEncoder;
use image::{ExtendedColorType, Rgb, RgbImage};
use instantlink_core::commands::{
    Command, INFO_IMAGE_SUPPORT, OP_DATA, OP_DOWNLOAD_CANCEL, OP_DOWNLOAD_END, OP_DOWNLOAD_START,
    OP_LED_PATTERN_SETTINGS, OP_PRINT_IMAGE, OP_SUPPORT_FUNCTION_INFO,
};
use instantlink_core::device::BlePrinterDevice;
use instantlink_core::protocol::{self, Packet, PacketAssembler};
use instantlink_core::transport::Transport;
use instantlink_core::{PrinterDevice, PrinterError, PrinterModel, Result};

fn fragment(data: &[u8], limit: usize) -> Vec<Vec<u8>> {
    protocol::fragment_with_size(data, NonZeroUsize::new(limit).unwrap())
}

#[test]
fn negotiated_mtu_selection_obeys_att_overhead_bounds_and_fallback() {
    assert_eq!(protocol::fragment_payload_size(None, false), 182);
    for invalid in [0, 1, 3, 20, 22, 518, 1000, u16::MAX] {
        assert_eq!(protocol::fragment_payload_size(Some(invalid), false), 182);
        assert_eq!(protocol::fragment_payload_size(Some(invalid), true), 182);
    }
    for mtu in 23u16..=517 {
        assert_eq!(
            protocol::fragment_payload_size(Some(mtu), false),
            usize::from(mtu - 3).min(236)
        );
        assert_eq!(
            protocol::fragment_payload_size(Some(mtu), true),
            usize::from(mtu - 3).min(182)
        );
    }
}

#[test]
fn diagnostic_ceiling_remains_mtu_bounded_independently_of_preferred_production_cap() {
    for mtu in [None, Some(0), Some(22), Some(518), Some(u16::MAX)] {
        for conservative in [false, true] {
            assert_eq!(protocol::fragment_payload_size(mtu, conservative), 182);
            assert_eq!(
                protocol::diagnostic_fragment_payload_size(mtu, conservative),
                182
            );
        }
    }
    for mtu in 23u16..=517 {
        assert_eq!(
            protocol::fragment_payload_size(Some(mtu), false),
            usize::from(mtu - 3).min(236)
        );
        assert_eq!(
            protocol::diagnostic_fragment_payload_size(Some(mtu), false),
            usize::from(mtu - 3).min(244)
        );
        assert_eq!(
            protocol::fragment_payload_size(Some(mtu), true),
            usize::from(mtu - 3).min(182)
        );
        assert_eq!(
            protocol::diagnostic_fragment_payload_size(Some(mtu), true),
            usize::from(mtu - 3).min(182)
        );
    }
    for (mtu, production, diagnostic) in [
        (23, 20, 20),
        (185, 182, 182),
        (235, 232, 232),
        (239, 236, 236),
        (247, 236, 244),
        (517, 236, 244),
    ] {
        assert_eq!(
            protocol::fragment_payload_size(Some(mtu), false),
            production
        );
        assert_eq!(
            protocol::diagnostic_fragment_payload_size(Some(mtu), false),
            diagnostic
        );
    }
}

#[test]
fn empty_and_max_protocol_packets_do_not_add_bytes_or_zero_length_writes() {
    for size in [0usize, 1, 181, 182, 183, 243, 244, 245, 65535] {
        let data: Vec<_> = (0..size).map(|index| (index % 251) as u8).collect();
        for limit in [20, 182, 236, 244] {
            let fragments = fragment(&data, limit);
            assert_eq!(fragments.len(), size.div_ceil(limit));
            assert!(
                fragments
                    .iter()
                    .all(|part| !part.is_empty() && part.len() <= limit)
            );
            assert_eq!(fragments.concat(), data);
        }
    }
}

fn asymmetric_jpeg(model: PrinterModel) -> Vec<u8> {
    let spec = model.spec();
    let image = RgbImage::from_fn(spec.width, spec.height, |x, y| {
        if x < spec.width / 4 && y < spec.height / 3 {
            Rgb([235, 30, 70])
        } else if y > spec.height * 2 / 3 {
            Rgb([15, 90, 190])
        } else {
            Rgb([100, 180, 40])
        }
    });
    let mut bytes = Vec::new();
    JpegEncoder::new_with_quality(&mut bytes, 80)
        .encode(
            image.as_raw(),
            spec.width,
            spec.height,
            ExtendedColorType::Rgb8,
        )
        .unwrap();
    assert!(bytes.len() <= spec.max_image_size);
    bytes
}

#[derive(Default)]
struct Capture {
    packets: Vec<Vec<u8>>,
    fragments: Vec<Vec<u8>>,
    pending_response: Option<Packet>,
    fail_next_data: bool,
}

struct FragmentedTransport {
    model: PrinterModel,
    fragment_limit: usize,
    state: Arc<Mutex<Capture>>,
    block_first_data: AtomicBool,
    data_entered: Arc<Notify>,
    data_release: Arc<Notify>,
}

#[async_trait]
impl Transport for FragmentedTransport {
    async fn send(&self, data: &[u8]) -> Result<()> {
        let packet = protocol::parse_packet(data).unwrap();
        {
            let mut state = self.state.lock().unwrap();
            state.packets.push(data.to_vec());
            let fragments = fragment(data, self.fragment_limit);
            if packet.opcode == OP_DATA && state.fail_next_data {
                state.fail_next_data = false;
                state.fragments.push(fragments[0].clone());
                return Err(PrinterError::Ble(
                    "injected failure after first data fragment".into(),
                ));
            }
            state.fragments.extend(fragments);
            state.pending_response = Some(match packet.opcode {
                OP_SUPPORT_FUNCTION_INFO => {
                    let spec = self.model.spec();
                    let mut payload = vec![0, INFO_IMAGE_SUPPORT];
                    payload.extend_from_slice(&(spec.width as u16).to_be_bytes());
                    payload.extend_from_slice(&(spec.height as u16).to_be_bytes());
                    Packet {
                        opcode: packet.opcode,
                        payload,
                    }
                }
                OP_LED_PATTERN_SETTINGS => Packet {
                    opcode: packet.opcode,
                    payload: vec![],
                },
                _ => Packet {
                    opcode: packet.opcode,
                    payload: vec![0],
                },
            });
        }
        if packet.opcode == OP_DATA && self.block_first_data.swap(false, Ordering::SeqCst) {
            self.data_entered.notify_one();
            self.data_release.notified().await;
        }
        Ok(())
    }

    async fn receive(&self, _timeout: Duration) -> Result<Packet> {
        self.state
            .lock()
            .unwrap()
            .pending_response
            .take()
            .ok_or(PrinterError::Timeout)
    }

    async fn send_and_receive(&self, data: &[u8], timeout: Duration) -> Result<Packet> {
        self.send(data).await?;
        self.receive(timeout).await
    }

    async fn disconnect(&self) -> Result<()> {
        Ok(())
    }

    fn model_number_hint(&self) -> Option<&str> {
        (self.model == PrinterModel::MiniLink3).then_some("FI033")
    }
}

async fn device(model: PrinterModel, limit: usize) -> (BlePrinterDevice, Arc<Mutex<Capture>>) {
    let (device, state, _, _) = device_with_gate(model, limit, false).await;
    (device, state)
}

async fn device_with_gate(
    model: PrinterModel,
    limit: usize,
    block: bool,
) -> (
    BlePrinterDevice,
    Arc<Mutex<Capture>>,
    Arc<Notify>,
    Arc<Notify>,
) {
    let state = Arc::new(Mutex::new(Capture::default()));
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let transport = FragmentedTransport {
        model,
        fragment_limit: limit,
        state: Arc::clone(&state),
        block_first_data: AtomicBool::new(block),
        data_entered: Arc::clone(&entered),
        data_release: Arc::clone(&release),
    };
    let device = BlePrinterDevice::new(Box::new(transport), "Independent transport test".into())
        .await
        .unwrap();
    (device, state, entered, release)
}

#[test]
fn every_model_data_packet_reassembles_identically_at_supported_fragment_limits() {
    for &model in PrinterModel::all() {
        let spec = model.spec();
        for size in [
            1,
            spec.chunk_size - 1,
            spec.chunk_size,
            spec.chunk_size + 1,
            spec.max_image_size,
        ] {
            let jpeg: Vec<u8> = (0..size).map(|index| (index % 251) as u8).collect();
            let mut reconstructed = Vec::new();
            for (index, chunk) in instantlink_core::image::chunk_image_data(&jpeg, model)
                .iter()
                .enumerate()
            {
                let encoded = Command::Data {
                    index: index as u32,
                    data: chunk.clone(),
                }
                .encode()
                .unwrap();
                assert_eq!(encoded.len(), chunk.len() + 11);
                for limit in [20, 182, 236, 244] {
                    let fragments = fragment(&encoded, limit);
                    assert!(
                        fragments
                            .iter()
                            .all(|fragment| !fragment.is_empty() && fragment.len() <= limit)
                    );
                    assert_eq!(fragments.concat(), encoded);
                    let mut assembler = PacketAssembler::new();
                    let mut completed = Vec::new();
                    for fragment in fragments {
                        if let Some(packet) = assembler.feed(&fragment).unwrap() {
                            completed.push(packet);
                        }
                    }
                    assert_eq!(completed.len(), 1);
                    assert_eq!(completed[0].opcode, OP_DATA);
                    assert_eq!(
                        u32::from_be_bytes(completed[0].payload[..4].try_into().unwrap()),
                        index as u32
                    );
                    assert_eq!(&completed[0].payload[4..], chunk);
                }
                reconstructed.extend_from_slice(chunk);
            }
            assert_eq!(
                &reconstructed[..jpeg.len()],
                jpeg,
                "JPEG must survive every model chunk boundary"
            );
            assert!(
                reconstructed[jpeg.len()..].iter().all(|byte| *byte == 0),
                "Only established last-chunk zero padding may follow the JPEG"
            );
            assert_eq!(
                reconstructed.len(),
                jpeg.len().div_ceil(spec.chunk_size) * spec.chunk_size
            );
        }
    }
}

#[test]
fn control_commands_keep_their_exact_wire_encoding_at_every_payload_limit() {
    let commands = [
        Command::DeviceInfo,
        Command::ImageSupportInfo,
        Command::BatteryStatus,
        Command::PrinterFunctionInfo,
        Command::HistoryInfo,
        Command::DownloadStart {
            image_size: 102846,
            print_option: 1,
        },
        Command::DownloadEnd,
        Command::DownloadCancel,
        Command::PrintImage,
        Command::LedPatternSettings {
            red: 248,
            green: 120,
            blue: 67,
            pattern: 0,
        },
        Command::Shutdown,
        Command::Reset,
    ];
    for command in commands {
        let encoded = command.encode().unwrap();
        let expected = protocol::parse_packet(&encoded).unwrap();
        for mtu in [
            None,
            Some(23),
            Some(185),
            Some(247),
            Some(517),
            Some(u16::MAX),
        ] {
            for conservative in [false, true] {
                let payload_limit = protocol::fragment_payload_size(mtu, conservative);
                let fragments = fragment(&encoded, payload_limit);
                assert_eq!(fragments.concat(), encoded);
                assert_eq!(
                    fragments.len(),
                    1,
                    "Control commands fit even the minimum ATT MTU"
                );
                assert_eq!(
                    protocol::parse_packet(&fragments[0]),
                    Some(expected.clone())
                );
            }
        }
    }
}

#[test]
fn square_data_packet_uses_eight_writes_at_244_instead_of_ten_at_182() {
    let packet = Command::Data {
        index: 0,
        data: vec![0x81; 1808],
    }
    .encode()
    .unwrap();
    assert_eq!(packet.len(), 1819);
    assert_eq!(fragment(&packet, 182).len(), 10);
    assert_eq!(fragment(&packet, 236).len(), 8);
    assert_eq!(fragment(&packet, 244).len(), 8);
    assert_eq!(fragment(&packet, 244).concat(), packet);
}

#[test]
fn preferred_236_preserves_write_count_and_avoids_244_acl_fragment_overhead() {
    // This device's HCI ACL data buffers carry27octets. Each separate ATT
    // WriteCommand adds3 ATT bytes and4 L2CAP bytes before ACL fragmentation.
    // Counts are a structural bound for that observed controller, not a timing claim.
    for &model in PrinterModel::all() {
        let command = Command::Data {
            index: 0,
            data: vec![0x81; model.spec().chunk_size],
        }
        .encode()
        .unwrap();
        let legacy = fragment(&command, 182);
        let preferred = fragment(&command, 236);
        let largest = fragment(&command, 244);
        assert_eq!(preferred.len(), largest.len());
        let acl_frames = |fragments: &[Vec<u8>]| {
            fragments
                .iter()
                .map(|piece| (piece.len() + 7).div_ceil(27))
                .sum::<usize>()
        };
        let counts = (
            acl_frames(&legacy),
            acl_frames(&preferred),
            acl_frames(&largest),
        );
        if model == PrinterModel::Square {
            assert_eq!(counts, (70, 70, 75));
        } else {
            assert_eq!(counts, (36, 35, 37));
        }
        assert!(counts.1 <= counts.0);
        assert!(counts.0 < counts.2);
        assert_eq!(preferred.concat(), command);
    }
}

#[tokio::test(start_paused = true)]
async fn full_prepared_print_preserves_exact_jpeg_and_same_commands_for_every_model() {
    for &model in PrinterModel::all() {
        let jpeg = asymmetric_jpeg(model);
        let mut legacy_packets = None;
        for limit in [182, 236, 244] {
            let (device, state) = device(model, limit).await;
            device
                .print_prepared_jpeg(&jpeg, model, model.spec().flip_vertical, 1, None)
                .await
                .unwrap();
            let state = state.lock().unwrap();
            let packets: Vec<_> = state
                .packets
                .iter()
                .map(|bytes| protocol::parse_packet(bytes).unwrap())
                .collect();
            let data: Vec<_> = packets
                .iter()
                .filter(|packet| packet.opcode == OP_DATA)
                .collect();
            let transferred: Vec<_> = data
                .iter()
                .flat_map(|packet| packet.payload[4..].iter().copied())
                .collect();
            assert_eq!(&transferred[..jpeg.len()], jpeg);
            assert!(transferred[jpeg.len()..].iter().all(|byte| *byte == 0));
            assert_eq!(
                transferred.len(),
                jpeg.len().div_ceil(model.spec().chunk_size) * model.spec().chunk_size
            );
            for (index, packet) in data.iter().enumerate() {
                assert_eq!(
                    u32::from_be_bytes(packet.payload[..4].try_into().unwrap()),
                    index as u32
                );
            }
            let start = packets
                .iter()
                .find(|packet| packet.opcode == OP_DOWNLOAD_START)
                .unwrap();
            assert_eq!(start.payload[1], 1);
            assert_eq!(
                u32::from_be_bytes(start.payload[4..8].try_into().unwrap()) as usize,
                jpeg.len()
            );
            assert_eq!(
                packets
                    .iter()
                    .filter(|packet| packet.opcode == OP_PRINT_IMAGE)
                    .count(),
                1
            );
            assert_eq!(
                packets
                    .iter()
                    .filter(|packet| packet.opcode == OP_DOWNLOAD_END)
                    .count(),
                1
            );
            assert!(
                !packets
                    .iter()
                    .any(|packet| packet.opcode == OP_DOWNLOAD_CANCEL)
            );
            assert_eq!(state.fragments.concat(), state.packets.concat());
            if let Some(expected) = &legacy_packets {
                assert_eq!(&state.packets, expected, "Only ATT boundaries may change");
            } else {
                legacy_packets = Some(state.packets.clone());
            }
        }
    }
}

#[tokio::test(start_paused = true)]
async fn partial_data_write_failure_cancels_download_once_and_never_executes_or_replays() {
    let model = PrinterModel::Square;
    let jpeg = asymmetric_jpeg(model);
    let (device, state) = device(model, 244).await;
    state.lock().unwrap().fail_next_data = true;
    let error = device
        .print_prepared_jpeg(&jpeg, model, false, 0, None)
        .await
        .unwrap_err();
    assert!(matches!(error, PrinterError::Ble(_)));
    let state = state.lock().unwrap();
    let opcodes: Vec<_> = state
        .packets
        .iter()
        .map(|bytes| protocol::parse_packet(bytes).unwrap().opcode)
        .collect();
    assert_eq!(
        opcodes,
        [
            OP_SUPPORT_FUNCTION_INFO,
            OP_DOWNLOAD_START,
            OP_DATA,
            OP_DOWNLOAD_CANCEL
        ]
    );
    assert_eq!(
        state.fragments.len(),
        4,
        "Model lookup, download start, one accepted data fragment, cancel"
    );
}

#[tokio::test(start_paused = true)]
async fn other_device_operations_cannot_interleave_with_a_fragmented_print() {
    let model = PrinterModel::Square;
    let jpeg = asymmetric_jpeg(model);
    let (device, state, entered, release) = device_with_gate(model, 244, true).await;
    let device = Arc::new(device);
    let print_device = Arc::clone(&device);
    let print = tokio::spawn(async move {
        print_device
            .print_prepared_jpeg(&jpeg, model, false, 0, None)
            .await
    });
    entered.notified().await;
    let led_device = Arc::clone(&device);
    let led = tokio::spawn(async move { led_device.set_led(1, 2, 3, 0).await });
    tokio::task::yield_now().await;
    {
        let state = state.lock().unwrap();
        assert_eq!(
            state
                .packets
                .iter()
                .map(|packet| protocol::parse_packet(packet).unwrap().opcode)
                .collect::<Vec<_>>(),
            [OP_SUPPORT_FUNCTION_INFO, OP_DOWNLOAD_START, OP_DATA]
        );
    }
    release.notify_one();
    print.await.unwrap().unwrap();
    led.await.unwrap().unwrap();
    let state = state.lock().unwrap();
    let opcodes: Vec<_> = state
        .packets
        .iter()
        .map(|packet| protocol::parse_packet(packet).unwrap().opcode)
        .collect();
    assert_eq!(
        &opcodes[opcodes.len() - 2..],
        &[OP_PRINT_IMAGE, OP_LED_PATTERN_SETTINGS]
    );
}

#[tokio::test(start_paused = true)]
async fn cancelled_print_future_never_replays_data_or_executes_physical_print() {
    let model = PrinterModel::Square;
    let jpeg = asymmetric_jpeg(model);
    let (device, state, entered, release) = device_with_gate(model, 244, true).await;
    let print = tokio::spawn(async move {
        device
            .print_prepared_jpeg(&jpeg, model, false, 0, None)
            .await
    });
    entered.notified().await;
    print.abort();
    assert!(print.await.unwrap_err().is_cancelled());
    release.notify_one();
    tokio::task::yield_now().await;
    let state = state.lock().unwrap();
    let opcodes: Vec<_> = state
        .packets
        .iter()
        .map(|packet| protocol::parse_packet(packet).unwrap().opcode)
        .collect();
    assert_eq!(
        opcodes,
        [OP_SUPPORT_FUNCTION_INFO, OP_DOWNLOAD_START, OP_DATA]
    );
}
