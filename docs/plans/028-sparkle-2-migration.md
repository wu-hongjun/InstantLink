# Plan 028: Sparkle 2 Auto-Update Migration

## Goal

Replace the hand-rolled auto-update logic in `AppRuntimeServices.swift` with the [Sparkle 2](https://sparkle-project.org/) framework. Sparkle gives us EdDSA signature verification, an audited install dance, an appcast-driven release feed, optional delta updates, and a UX that we no longer have to maintain.

## Why Now

Plan 018 shipped SHA-256 verification and TOCTOU isolation, which are sound for an indie distribution but still leave us:

- maintaining bespoke `URLSession` + `hdiutil` + `cp -R` + relaunch logic
- relying on an attacker not also being able to publish a matching `.sha256` (our integrity check trusts the same release page that hosts the artifact)
- with no built-in story for delta updates, background checks, or a "skip this version" UX

Sparkle's EdDSA model raises the bar: the public key is baked into the running app, and any update payload not signed by the matching private key is rejected at install time, regardless of where it was hosted.

## Threat Model Improvements

| Threat | Today (Plan 018) | After Sparkle 2 |
|---|---|---|
| Attacker hijacks the GitHub release page (or its CDN) and serves a tampered DMG **and** a matching `.sha256` | Installs successfully | Rejected — signature does not match the baked-in public key |
| Attacker MITMs the appcast/release feed | Mitigated by HTTPS only | Mitigated by HTTPS **and** EdDSA |
| Attacker compromises the build machine and steals the SHA-256 generation step | Tampered DMG installs | Tampered DMG installs **only if** the attacker also has the EdDSA private key (held offline / in CI secret) |
| Local user with same UID swaps DMG between verify and mount | Closed by Plan 018's staging dir | Closed by Sparkle's atomic install pipeline |

## Architecture Changes

### Today

`AppUpdateService` (in `AppRuntimeServices.swift`):

1. Hits the GitHub Releases API.
2. Downloads the DMG and its `.sha256` sibling.
3. Verifies the digest, isolates the DMG into a `0700` staging dir.
4. `hdiutil attach` → copy `.app` → `hdiutil detach` → relaunch.

### Proposed

Sparkle's `SPUStandardUpdaterController` owns the lifecycle:

1. Polls our appcast XML feed on a schedule (and on demand from the Settings panel).
2. Fetches the DMG that the appcast points at.
3. Verifies the EdDSA signature embedded in the appcast `<enclosure>`.
4. Mounts, copies, and relaunches via Sparkle's hardened install path.
5. Surfaces UI through Sparkle's standard sheet (dismiss, install, skip-version, install-on-quit).

We can keep our existing GitHub Releases publishing flow — the appcast feed is just an XML file we serve from the same repo (`gh-pages` already publishes documentation).

## Implementation Scope

### Build & dependency

- Add Sparkle (Swift Package) as a dependency. We currently build with `swiftc` directly, no Xcode project — adding an SPM dependency means either:
  - migrating the build to `swift build` against a `Package.swift`, or
  - vendoring the Sparkle XCFramework and linking it manually inside `scripts/build-app.sh`.
- Update `scripts/build-app.sh` to copy the Sparkle XPC services (`Autoupdate.app`, `Updater.app`) into `Contents/Frameworks/`. Sparkle 2 requires both bundles to live inside the host app's framework directory.
- Update `Info.plist`:
  - `SUFeedURL` → URL of our appcast XML feed
  - `SUPublicEDKey` → base64-encoded EdDSA public key
  - `SUEnableAutomaticChecks` → `YES`
  - `LSMinimumSystemVersion` stays at our current macOS 15 baseline

### Swift code

- Replace `AppUpdateService` (and its consumers in `ViewModel.swift`) with `SPUStandardUpdaterController`.
- Keep a thin Swift wrapper so `Settings → Check for Updates Now` still works (call `updater.checkForUpdates(nil)`).
- Drop:
  - `verifyAndInstall` and the SHA-256 helpers
  - `installDownloadedApp`, the `hdiutil` shell-out
  - the localized `update_error_*` strings (Sparkle owns the UI now)
- Keep:
  - relaunch helper logic if Sparkle's relaunch hook needs custom behavior (likely unneeded)
  - the existing `Localizable.strings` keys for non-update flows

### Release pipeline

- Generate an EdDSA keypair **once** with `Sparkle.app/Contents/MacOS/generate_keys`. Store the private key in the macOS keychain (or 1Password). Bake the public key into `Info.plist`.
- Add a release step in `.github/workflows/release.yml`:
  1. Build `.app` and DMG (existing).
  2. Run `sign_update <DMG> -f <private-key>` to produce the EdDSA signature.
  3. Generate / append an appcast entry referencing the signed DMG.
  4. Commit the updated appcast to `gh-pages` (or upload as a release asset alongside the DMG).
- The private key MUST live in a CI secret (`SPARKLE_ED_PRIVATE_KEY`). Document the rotation procedure in `docs/development/release.md`.

## Appcast Feed

Host at `https://wu-hongjun.github.io/InstantLink/appcast.xml` (already served via `mkdocs gh-deploy`) so we do not need a separate web property.

Schema (per Sparkle 2 docs):

```xml
<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">
  <channel>
    <title>InstantLink Updates</title>
    <item>
      <title>Version 0.2.0</title>
      <pubDate>Fri, 02 May 2026 00:00:00 +0000</pubDate>
      <enclosure
        url="https://github.com/wu-hongjun/InstantLink/releases/download/v0.2.0/InstantLink-0.2.0.dmg"
        sparkle:version="0.2.0"
        sparkle:edSignature="..."
        length="12345678"
        type="application/octet-stream"/>
    </item>
  </channel>
</rss>
```

## Migration Strategy

1. **Co-existence release** (`0.1.7`):
   - Ship Sparkle bundled but disabled (`SUEnableAutomaticChecks=NO`).
   - Keep the legacy `AppUpdateService` as the active updater.
   - This release lays down the public key in the install base, so 0.1.8+ can rely on it.
2. **Cutover release** (`0.1.8`):
   - Enable Sparkle (`SUEnableAutomaticChecks=YES`).
   - Strip `AppUpdateService` and the legacy code paths.
   - Publish the first signed appcast entry.
3. **Cleanup release** (`0.1.9`):
   - Remove the dead code paths kept in step 2 for safety.
   - Delete the `update_error_*` localized strings.

This three-step rollout protects against a Sparkle bug bricking auto-update — if 0.1.8 misbehaves, users on 0.1.7 still get updates via the legacy code, and we can cut 0.1.7.1 with a fix.

## Testing

### Manual

- Local appcast served via `python3 -m http.server`; point `SUFeedURL` at it. Verify:
  - matching signature → installs
  - tampered DMG → rejected with explicit error
  - tampered appcast (signature stripped) → rejected
  - skip-version → version remembered across launches
- Verify the UI looks correct in both light and dark mode, RTL (Arabic, Hebrew) layouts, and at large accessibility text sizes.

### Automated

- A CI step that runs `sparkle-validator` (or `Sparkle.app/Contents/MacOS/sign_update -p` to verify a signature against a known-good DMG) on every appcast push.
- Existing localization check script needs an update: any `update_error_*` keys we drop should not flag as missing.

## Risks

- **Build complexity:** moving away from a pure `swiftc` invocation is a one-way door. Plan time to update `build-app.sh` and the release workflow, and budget for the first release taking longer than expected.
- **Private-key custody:** if the EdDSA private key is lost, the install base cannot receive future updates without an out-of-band public-key rotation. Store it in two locations (1Password vault + offline backup) before the first signed release.
- **Sparkle XPC services:** these run as separate processes and need to be ad-hoc-signed (or, eventually, Developer ID-signed) consistently with the host app. Mismatched signatures cause silent update failures.
- **Appcast hosting:** if `gh-pages` is rate-limited or blocked, updates stall silently. Mitigate by also publishing the appcast as a release asset.

## Rollout Order

1. Generate the EdDSA keypair; store the private key in 1Password and a CI secret.
2. Migrate `build-app.sh` to bundle the Sparkle XCFramework + XPC services.
3. Add Sparkle to the Swift code path behind `SUEnableAutomaticChecks=NO`.
4. Cut 0.1.7 with Sparkle dormant.
5. Stand up the appcast feed and the `sign_update` step in `.github/workflows/release.yml`.
6. Cut 0.1.8 with Sparkle live and the legacy updater removed.
7. Cut 0.1.9 to clean up dead code and stale localization keys.

## Exit Criteria

- An attacker who controls the GitHub release page but not the EdDSA private key cannot ship a malicious update.
- Auto-update no longer relies on hand-rolled `hdiutil`/`cp -R` logic.
- Update UI is feature-complete (skip version, install on quit, manual check) without our maintaining it.
- The release workflow signs every artifact with EdDSA and publishes a matching appcast entry.
- Key rotation, appcast hosting, and signing prerequisites are documented in `docs/development/release.md`.
