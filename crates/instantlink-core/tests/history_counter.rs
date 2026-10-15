//! Compatibility regression for Square Link's observed 32-bit history counter.
use instantlink_core::commands::{INFO_PRINT_HISTORY, OP_SUPPORT_FUNCTION_INFO, Response};
use instantlink_core::protocol::Packet;

fn packet(data: &[u8]) -> Packet {
    let mut payload = vec![0, INFO_PRINT_HISTORY];
    payload.extend_from_slice(data);
    Packet {
        opcode: OP_SUPPORT_FUNCTION_INFO,
        payload,
    }
}

fn assert_count(data: &[u8], expected: u16) {
    assert_eq!(
        Response::decode(&packet(data)),
        Response::HistoryInfo { count: expected }
    );
}

#[test]
fn observed_square_counter_reads_first_complete_u32_instead_of_high_u16() {
    assert_count(&[0, 0, 0, 0x43, 0, 0, 0, 0x12], 67);
    assert_count(&[0, 0, 0, 0x43, 0xff, 0xff, 0xff, 0xff], 67);
}

#[test]
fn exact_legacy_u16_counts_keep_existing_public_contract() {
    for count in [0u16, 42, 67, 255, 256, u16::MAX] {
        assert_count(&count.to_be_bytes(), count);
    }
}

#[test]
fn observed_square_counts_preserve_full_supported_u16_range() {
    for count in [0u16, 42, 67, 255, 256, u16::MAX] {
        let mut data = u32::from(count).to_be_bytes().to_vec();
        data.extend_from_slice(&[0, 0, 0, 0x12]);
        assert_count(&data, count);
    }
}

#[test]
fn overflowing_32_bit_counters_never_wrap_or_silently_read_the_high_half() {
    for count in [65536u32, 65536 + 67, u32::MAX] {
        let mut data = count.to_be_bytes().to_vec();
        data.extend_from_slice(&[0, 0, 0, 0x12]);
        let packet = packet(&data);
        assert_eq!(
            Response::decode(&packet),
            Response::Unknown {
                opcode: packet.opcode,
                payload: packet.payload
            }
        );
    }
}

#[test]
fn ambiguous_or_truncated_history_data_is_not_guessed_as_a_counter() {
    for length in [0, 1, 3, 4, 5, 6, 7, 9, 10, 16] {
        let packet = packet(&vec![0x43; length]);
        assert_eq!(
            Response::decode(&packet),
            Response::Unknown {
                opcode: packet.opcode,
                payload: packet.payload
            }
        );
    }
}

#[test]
fn nonzero_status_cannot_return_an_apparently_valid_square_counter() {
    let mut packet = packet(&[0, 0, 0, 0x43, 0, 0, 0, 0x12]);
    packet.payload[0] = 1;
    assert_eq!(
        Response::decode(&packet),
        Response::Unknown {
            opcode: packet.opcode,
            payload: packet.payload
        }
    );
}
