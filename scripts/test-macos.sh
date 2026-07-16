#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="$REPO_ROOT/target/macos-tests"
MODULE_CACHE="${TMPDIR:-/tmp}/instantlink-swift-test-module-cache"
SDK_PATH="$(xcrun --sdk macosx --show-sdk-path)"
PLATFORM_PATH="$(xcrun --sdk macosx --show-sdk-platform-path)"
PLATFORM_FRAMEWORKS="$PLATFORM_PATH/Developer/Library/Frameworks"
TEST_BIN="$BUILD_DIR/InstantLinkMacTests"

mkdir -p "$BUILD_DIR" "$MODULE_CACHE"

SOURCES=(
  "$REPO_ROOT/macos/InstantLink/Localization.swift"
  "$REPO_ROOT/macos/InstantLink/Support/BrandColor.swift"
  "$REPO_ROOT/macos/InstantLink/OverlayModels.swift"
  "$REPO_ROOT/macos/InstantLink/InstantLinkFFI.swift"
  "$REPO_ROOT/macos/InstantLink/Features/Editor/State/AdjustmentState.swift"
  "$REPO_ROOT/macos/InstantLink/Features/Editor/State/CropState.swift"
  "$REPO_ROOT/macos/InstantLink/Features/Editor/State/AdjustmentHistory.swift"
  "$REPO_ROOT/macos/InstantLink/Features/Editor/Pipeline/Sections/BlackAndWhitePipeline.swift"
  "$REPO_ROOT/macos/InstantLink/Core/AppModels.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeFirmwareBundle.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeConfig.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeModels.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeConfigSchema.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeAuth.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeClientFileStore.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeServerClock.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeTransport.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeHTTPTransport.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeControlCoordinator.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeUpdateCoordinator.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeBackupCoordinator.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeDiagnosticsCoordinator.swift"
  "$REPO_ROOT/macos/InstantLink/Core/BridgeSettingsDraft.swift"
  "$REPO_ROOT/macos/InstantLink/Core/AppRuntimeServices.swift"
  "$REPO_ROOT/macos/InstantLink/Core/QueueEditCoordinator.swift"
  "$REPO_ROOT/macos/InstantLink/Core/PrinterConnectionCoordinator.swift"
)

while IFS= read -r source; do
  SOURCES+=("$source")
done < <(find "$REPO_ROOT/macos/InstantLink/Features/Bridge" -name '*.swift' | sort)

TESTS=()
while IFS= read -r test_source; do
  TESTS+=("$test_source")
done < <(find "$REPO_ROOT/macos/Tests" -maxdepth 1 -name '*.swift' | sort)

swiftc \
  -sdk "$SDK_PATH" \
  -target arm64-apple-macosx15.0 \
  -module-cache-path "$MODULE_CACHE" \
  -O \
  -F "$PLATFORM_FRAMEWORKS" \
  -o "$TEST_BIN" \
  "${SOURCES[@]}" \
  "${TESTS[@]}" \
  -framework AppKit \
  -framework SwiftUI \
  -framework Security \
  -framework CoreText \
  -framework CoreImage

"$TEST_BIN"
