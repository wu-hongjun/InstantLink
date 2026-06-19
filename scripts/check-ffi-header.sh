#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEADER="crates/instantlink-ffi/include/instantlink.h"
GENERATED_DIR="$(mktemp -d "${TMPDIR:-/tmp}/instantlink-ffi-header.XXXXXX")"
GENERATED_HEADER="$GENERATED_DIR/instantlink.h"
trap 'rm -rf "$GENERATED_DIR"' EXIT

INSTANTLINK_HEADER_OUT="$GENERATED_HEADER" cargo build -p instantlink-ffi --locked "$@"

if cmp -s "$GENERATED_HEADER" "$HEADER"; then
  exit 0
fi

echo "error: generated FFI header differs from ${HEADER}" >&2
echo "Regenerate it with:" >&2
printf '  INSTANTLINK_UPDATE_HEADER=1 cargo build -p instantlink-ffi --locked' >&2
for arg in "$@"; do
  printf ' %q' "$arg" >&2
done
printf '\n\n' >&2
diff -u "$HEADER" "$GENERATED_HEADER" >&2 || true
exit 1
