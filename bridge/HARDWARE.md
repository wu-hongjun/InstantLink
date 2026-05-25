# Hardware

## BOM

Prices are planning estimates captured for the November 2025 hardware plan; verify before purchase.

| Item | Exact part / SKU | Qty | Est. USD | Notes |
| --- | --- | ---: | ---: | --- |
| Compute | Raspberry Pi Zero 2 W | 1 | 15.00 | BCM2710A1, 512 MB RAM, Wi-Fi 4, BLE 4.2 |
| Headered compute option | Raspberry Pi Zero 2 WH | 1 | 18-20 | Useful if avoiding soldering |
| Display/input | Waveshare 1.3inch LCD HAT, ST7789VW, 240x240 | 1 | 13.99 | SPI0 CE0, joystick, KEY1/2/3 |
| Battery | SupTronics/Geekworm X306 V1.5 18650 UPS shield | 1 | 24-35 | One-cell 18650 UPS, USB-C power input, LEDs, hardware button, no host fuel gauge |
| microSD | SanDisk Industrial 32 GB A1 or equivalent | 1 | 8-12 | Prefer high-endurance media |
| Cable | USB-C male to micro-USB OTG/data cable | 1 | 6-12 | Must preserve D+/D-, ground, and host attach/VBUS signaling |
| Mount | SmallRig 761 cold shoe to 1/4"-20 adapter | 1 | 4.99 | Hot-shoe/cold-shoe mounting path |
| Insert | Heat-set brass 1/4"-20 insert or nut plate | 1 | 2-5 | For printed enclosure |
| Fasteners | M2.5 standoffs/screws, nylon preferred | 1 set | 3-6 | Match final enclosure height |
| Enclosure | Custom print derived from Thingiverse #3334127 | 1 | 3-10 | Requires adaptation for LCD HAT and X306 |

Expected one-off hardware total: about USD 95-125 before printer, film, camera, shipping, tax, and spare cables.

## BOM Reference Links

- Raspberry Pi Zero 2 W product page: `https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/`
- Waveshare 1.3inch LCD HAT product page: `https://www.waveshare.com/product/raspberry-pi/displays/1.3inch-lcd-hat.htm`
- Geekworm/SupTronics X306 wiki: `https://wiki.geekworm.com/X306`
- SmallRig 761 reference listing: `https://www.bhphotovideo.com/c/product/1422144-REG/smallrig_761_cold_shoe_to_1_4.html`

## LCD HAT Pinout

| Function | Raspberry Pi pin | BCM GPIO | Notes |
| --- | ---: | ---: | --- |
| SPI SCLK | Pin 23 | GPIO11 | SPI0 SCLK |
| SPI MOSI | Pin 19 | GPIO10 | SPI0 MOSI |
| SPI CE0 | Pin 24 | GPIO8 | Display chip select |
| LCD DC | Pin 22 | GPIO25 | Data/command |
| LCD RST | Pin 13 | GPIO27 | Reset |
| LCD BL | Pin 18 | GPIO24 | Backlight PWM/on-off |
| Joystick up | Pin 31 | GPIO6 | gpiozero input |
| Joystick down | Pin 35 | GPIO19 | gpiozero input |
| Joystick left | Pin 29 | GPIO5 | gpiozero input |
| Joystick right | Pin 37 | GPIO26 | gpiozero input |
| Joystick press | Pin 33 | GPIO13 | gpiozero input |
| KEY1 | Pin 40 | GPIO21 | UI action |
| KEY2 | Pin 38 | GPIO20 | Cancel print during preview |
| KEY3 | Pin 36 | GPIO16 | Long-press pair new printer |
| 3V3 | Pin 1/17 | 3.3 V | Display logic |
| 5V | Pin 2/4 | 5 V | HAT power path |
| GND | multiple | GND | Shared ground |

## Wiring and Stack-Up

The intended physical stack is:

1. Raspberry Pi Zero 2 W as the center board.
2. X306 UPS shield mounted with its 18650 cell and pogo/header power path aligned.
3. Waveshare 1.3" LCD HAT mounted on the 40-pin GPIO header.
4. Enclosure retaining all boards without compressing the 18650 cell.

No soldered signal wiring should be required if using a headered Pi. Validate the USB-C to micro-USB OTG/data cable before camera testing: keep D+, D-, GND, shield, and OTG behavior intact, and preserve enough host attach/VBUS signaling for the Pi gadget controller to leave `not attached`. The Pi must be powered from the X306 USB-C/input path and 18650 cell; the camera link must not be treated as the bridge power source.

## Assembly Steps

1. Flash Raspberry Pi OS Lite 64-bit Trixie to microSD.
2. Solder or select a 40-pin header on the Pi Zero 2 W.
3. Test boot the Pi from bench power before attaching add-ons.
4. Attach the X306 UPS shield, install a quality flat-top 18650 cell, and verify the hardware button boots the Pi.
5. Attach the Waveshare LCD HAT to the GPIO header.
6. Confirm I2C, SPI, and Bluetooth are visible from the OS before enclosure installation.
7. Fit into the enclosure, leaving access to X306 power, USB data, SD card, and LCD buttons.
8. Use SmallRig 761 or a belt clip depending on camera handling preference.

## Enclosure Notes

Thingiverse #3334127 is the starting point because it is already a compact Pi Zero enclosure class. It will need mechanical changes for:

- X306 back thickness, 18650 cell access, charge LEDs, and hardware power button.
- LCD HAT front window and button/joystick clearance.
- USB data cable strain relief.
- 1/4"-20 insert or captive nut for SmallRig 761 mounting.
- Venting near the Pi SoC while preserving pocket safety.

## Cable Specification

- Camera end: USB-C male.
- Bridge end: micro-USB male into the Pi Zero data/OTG port, not the power-only port.
- Data: USB 2.0 D+/D- connected.
- Ground: connected.
- VBUS/attach: preserve the host attach signal required for Pi gadget enumeration. Do not use a charge-only cable or a cable with VBUS fully removed until a hardware-specific attach workaround has been validated.
- Role: Pi is the USB gadget; camera is the USB host.
