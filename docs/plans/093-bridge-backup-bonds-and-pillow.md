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
