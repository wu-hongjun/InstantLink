# Bridge pairing backups and Pillow cleanup

## Scope

Remove redundant Pillow RGB mode arguments without changing prepared image pixels. Include the
selected Printer's persisted BlueZ pairing information in management backups when it exists,
while preserving automatic reconnect and keeping pairing secrets out of logs and diagnostics.
Validate on the installed Bridge using status requests only, with no film consumed.

## Findings and implementation

- Hue and vignette processing supply three-channel `uint8` arrays. Pillow infers RGB; the explicit
  mode argument is redundant and emits deprecation warnings.
- The management backup paths previously used the installation directory as a filesystem root.
  The unprivileged management service also cannot read BlueZ's root-only storage. Adding a path
  alone would not make production pairing backups work.
- Use a socket-activated, narrowly scoped root backup broker with trusted root-owned code and
  root-only archives. Keep the management service unprivileged and retain `NoNewPrivileges`.
- Select only saved Printer pairing information, reject unsafe paths, and avoid copying unrelated
  devices or scan caches. Absence of a persistent bond is valid: Instax Link devices can reconnect
  using the saved Printer selection without an OS-level bond.

Storage layout and reload behavior were checked against the upstream
[BlueZ 5.82 storage reference](https://raw.githubusercontent.com/bluez/bluez/5.82/doc/settings-storage.txt).
BlueZ loads persisted state during object initialization, so a live bond restore must reload
BlueZ while the Bridge runtime is stopped.

## Validation

The Pillow implementation passed 335 affected imaging/pipeline tests with deprecation warnings
treated as errors. Six seeded profiles produce exactly the same RGB pixels as the previous
explicit-mode conversion and leave source pixels unchanged.

The independent source review passed 91 focused backup/broker/installer/Pillow tests and two
additional adversarial source/restore symlink-swap checks. Review fixes cover descriptor-relative
I/O, competing archive creation, private ownership, service recovery on failure, adapter identity
conflicts, legacy bundles and HTTP 404 compatibility. Production create/restore and pre-update
backups now use the same private broker. The App's existing backup/restore response models were
reviewed; their required fields remain unchanged.

Ruff, full formatting (158 files), strict mypy (68 source files), touched shell syntax, broker
compilation and strict docs passed. The first full test run passed 2,430 tests and found one
offline-provision fixture that lacked a mocked root identity for the new privileged installer.
Only eight expected host GPIO fallback warnings remain; Pillow warnings are gone. Final full
validation and installed results follow after that fixture is updated.

Real pairing secrets and backup archives remain on the Bridge; committed evidence contains
only verification results and measurements. Physical hardware: Raspberry Pi Zero 2 W Rev 1.0,
ST7789 LCD, Debian 13.2, Linux 6.12.47+rpt-rpi-v8, Python 3.13.5, BlueZ 5.82 and Link Square
INSTAX-52006924. No film, image, reset or actuator commands are permitted in this validation.

### Installed restore ownership refinement

The corrected offline fixture passed its 20 affected cases. Normal commit gates then passed
all 2,431 Bridge tests, with only eight expected host GPIO fallback warnings. Clean `870fb21`
was installed along with the root-owned helper, and the manager was restarted to load its client.

Production create/restore ran under an `ib` systemd sandbox matching the manager restrictions.
It verified and restored 28 files in 2.112/16.786 seconds from dispatch to reply; the broker
reported 321/14,916 ms for its operation intervals. Configuration, selection and native-library
contents remained unchanged. The isolated synthetic LTK/adapter identity roundtrip passed exact
bytes, private permissions and unrelated-device exclusion. The physical Printer has no persisted
bond, so its live backup correctly included selection and zero BlueZ files.

The subsequent application log check found a real ownership defect: private `presets.toml`
retained mode 0600 but became root-owned, preventing the runtime from loading it. The Bridge was
recovered by restoring its `ib` ownership and restarting. The final code now restores product
configuration files as `ib:ib` while keeping their private modes. Review also required repairing
nested product directory access. BlueZ keys and OS configuration outside the product directory
retain root ownership. A regression test covers private presets and nested credentials.

The independent ownership refinement review passed 92 focused tests with deprecations treated
as errors. Repeat installed restore and normal runtime acceptance follow below; the initial
integrity-only live result is preserved separately and is not final acceptance.

Clean ownership refinement `1a0c4b2` passed all 2,432 Bridge tests and was installed. Repeated
production backup/restore verified 28 files in 2.978/14.925 seconds from dispatch to reply.
Private presets remained `ib`-owned, readable and mode 0600; contents, selection and native
library remained unchanged. Both normal services were active with zero automatic restarts.
PID 9078 had zero warnings/errors, locked 600 MHz/backlight low, FTP 220/200, no throttling,
and no active backup worker. Isolated synthetic LTK/adapter identity restoration passed again.

The installed Pi Pillow 11.3.0 passed the six-profile exact RGB pixel comparison with warnings
treated as errors; no source pixels changed and no film was used.

### Preserve active firmware provenance

The final review identified another correctness issue: archives contain deployment fingerprints
but no matching firmware/native binaries. Applying an older configuration backup must not
overwrite the installed build's provenance. The broker now verifies the complete archive,
including these contextual metadata files, then omits `.deployment` entries from the live apply
plan. Counts and restored paths describe only applied files. Existing or absent deployment
records remain unchanged; modified contextual metadata still fails integrity verification before
services stop. Generic isolated-root archive restoration remains available for recovery tooling.

The independent final source review passed 95 focused tests with deprecations treated as errors.
The prior ownership live check predates this filter; final installed filtered-restore results follow.
