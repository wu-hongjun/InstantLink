//! Local CPU/allocation benchmark; no Bluetooth or Printer is used.
//! Run with `cargo run -p instantlink-core --release --locked --example protocol_assembly_benchmark`.
use std::alloc::{GlobalAlloc, Layout, System};
use std::hint::black_box;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::Instant;

use instantlink_core::protocol::{MAX_PACKET_PAYLOAD, PacketAssembler, build_packet, parse_packet};

struct CountingAllocator;
static ALLOCATIONS: AtomicUsize = AtomicUsize::new(0);

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        unsafe { System.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        ALLOCATIONS.fetch_add(1, Ordering::Relaxed);
        unsafe { System.realloc(ptr, layout, size) }
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn feed(assembler: &mut PacketAssembler, input: &[u8], fragment_size: usize) {
    for part in input.chunks(fragment_size) {
        black_box(assembler.feed(black_box(part)).unwrap());
    }
}

fn run(name: &str, payload_len: usize, fragment_size: usize, iterations: usize) {
    let payload: Vec<u8> = (0..payload_len).map(|i| (i * 37 + 11) as u8).collect();
    let input = build_packet(0x3001, &payload).unwrap();
    // Validate the same production path that is timed, outside the timed region.
    let mut assembler = PacketAssembler::new();
    let mut actual = None;
    for part in input.chunks(fragment_size) {
        let next = assembler.feed(part).unwrap();
        if next.is_some() {
            assert!(actual.is_none());
            actual = next;
        }
    }
    assert_eq!(actual, parse_packet(&input));
    assert!(assembler.feed(&[]).unwrap().is_none());
    let start_allocations = ALLOCATIONS.load(Ordering::Relaxed);
    feed(&mut assembler, &input, fragment_size);
    let allocations = ALLOCATIONS.load(Ordering::Relaxed) - start_allocations;
    for _ in 0..1000 {
        feed(&mut assembler, &input, fragment_size);
    }
    let mut times = Vec::new();
    for _ in 0..9 {
        let start = Instant::now();
        for _ in 0..iterations {
            feed(&mut assembler, &input, fragment_size);
        }
        times.push(start.elapsed().as_nanos() as f64 / iterations as f64);
    }
    times.sort_by(f64::total_cmp);
    println!(
        "{name}: payload={payload_len} fragment={fragment_size} iterations={iterations} allocations/packet={allocations} ns/packet min={:.2} median={:.2} max={:.2}",
        times[0], times[4], times[8]
    );
}

fn main() {
    run("empty-response", 0, 182, 500_000);
    run("indexed-ack", 5, 182, 500_000);
    run("status-response", 18, 182, 500_000);
    run("fragmented-1KiB", 1024, 182, 100_000);
    run("max-packet-stress", MAX_PACKET_PAYLOAD, 182, 2_000);
}
