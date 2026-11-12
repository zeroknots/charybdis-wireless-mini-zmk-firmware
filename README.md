[![.github/workflows/build.yml](https://github.com/280Zo/charybdis-wireless-mini-zmk-firmware/actions/workflows/build.yml/badge.svg)](https://github.com/280Zo/charybdis-wireless-mini-zmk-firmware/actions/workflows/build.yml)

## Intro

This repository offers pre-configured ZMK firmware designed for [Wireless Charybdis keyboards](https://github.com/280Zo/charybdis-wireless-mini-3x6-build-guide?tab=readme-ov-file). It supports both Bluetooth/USB and Dongle configurations and uses the latest input listener and processors to act as a bridge between the trackball and the rest of the system.

If you want to customize things the repo is set up to build through GitHub Actions (just clone and run it), or you can use the
containerized build script that will build all firmwares locally with a single command.


## Linux and NixOS

Use **`charybdis-qwerty-linux-bt`** for direct Bluetooth or a USB cable to one half.
The `bt` bundle contains `charybdis_left.uf2` and `charybdis_right.uf2`. It is not
limited to wireless use. Do not select the `dongle` bundle for this setup.

The active sources are in [config/keymap](config/keymap):

- [qwerty-linux.keymap](config/keymap/qwerty-linux.keymap) selects Linux shortcuts.
- [qwerty.keymap](config/keymap/qwerty.keymap) preserves the macOS shortcuts.
- [qwerty.dtsi](config/keymap/qwerty.dtsi) shares the physical layout, layers and timing.
- `qwerty-link.keymap` is an older independent variant. Do not edit it for this port.

The older copies in `config/` and `config/boards/`, and the upstream layer overview
below, do not describe the active Linux keymap.

### Linux shortcuts

| Action | Gesture | Output |
| --- | --- | --- |
| Copy / paste in GUI apps | Hold C / V | Ctrl+C / Ctrl+V |
| Close / open a browser tab | Hold W / T | Ctrl+W / Ctrl+T |
| Focus the browser address bar | Hold L | Ctrl+L |
| Copy / paste in Foot | Hold semicolon, then tap C / V | Ctrl+Shift+C / Ctrl+Shift+V |
| Open the desktop launcher | Press thumb keys 37 and 40 together | Super+Space |
| Select workspace 1–5 | Hold semicolon, then press A/S/D/F/G | Super+1–5 |
| Hold Super | Hold the far-right slash key | Right Super |

Tapping C, V, W, T and L still types the letter. Shortcut holds retain the existing
290 ms, tap-preferred behavior. The firmware cannot detect the focused application.
In a terminal, Ctrl+C can interrupt a command. Use the explicit terminal clipboard
shortcuts instead. Trackball settings and the other key positions are unchanged.

### Nix integration

[zeroknots/nix](https://github.com/zeroknots/nix) declares this repository in its
personal repository list. After the Nix change is merged and each host is activated,
the existing repository service clones missing checkouts into
`/repos/private/charybdis-wireless-mini-zmk-firmware` and registers the personal T3
project. It does not pull existing checkouts, build firmware, or flash devices.
NixOS activation does not modify keyboard pairings or firmware.

Keep desktop and terminal bindings in the Nix repository. Keep firmware in this
repository. Both macOS and Linux variants remain available through the existing CI.

### Verify and flash the Linux variant

Keep another keyboard available. Flashing temporarily disconnects the keyboard and
replaces its firmware. Save a known-good `qwerty-bt` bundle before proceeding.
Do not flash `settings_reset` or clear Bluetooth profiles for this keymap-only change.
Those operations can erase settings and require pairing again.

1. Run `python3 -I scripts/test_keymaps.py` from this repository with Python 3 and `cpp` available.
   The tests check staged includes, shortcut positions, legacy compatibility and matrix discovery.
   They stub upstream headers and do not replace a firmware build.
2. Open this repository's [Actions page](https://github.com/zeroknots/charybdis-wireless-mini-zmk-firmware/actions/workflows/build.yml).
3. Select a successful run for the exact commit you intend to flash.
4. Download the `charybdis-qwerty-linux-bt` artifact from that run.
5. Extract the artifact into a new directory.
6. Connect the left half by USB.
7. Double-press its reset button to mount the bootloader volume.
8. Copy `charybdis_left.uf2` to that volume. The device should restart and unmount.
9. Connect the right half by USB.
10. Double-press its reset button to mount the bootloader volume.
11. Copy `charybdis_right.uf2` to that volume. The device should restart and unmount.
12. Verify typing, GUI shortcuts, Foot clipboard shortcuts, Super+Space and trackball behavior over USB.
13. Verify the same behavior over the existing Bluetooth connection with the USB cable disconnected.

If a device does not restart or the halves do not reconnect, stop before clearing
settings. To roll back, flash the corresponding left and right files from the
saved `qwerty-bt` bundle. If ZMK Studio overrides are present, they can take priority
over compiled defaults. Inspect them before considering a settings reset.

## Quick Start

### Flashing the Firmware

Download your choice of firmware from the Releases page. Choose a combination of format (Bluetooth/Dongle) and layout (QWERTY, etc.), then follow the steps below to flash it to your keyboard

1. Unzip the firmware zip
2. Plug the right half into the computer through USB
3. Double press the reset button
4. The keyboard will mount as a removable storage device
5. Copy the applicable uf2 file into the NICENANO storage device (e.g. charybdis_qwerty_dongle.uf2 -> dongle)
6. It will take a few seconds, then it will unmount and restart itself.
7. Repeat these steps for all devices.
8. You should now be able to use your keyboard

> [!NOTE]  
> If you are flashing the firmware for the first time, or if you're switching between the dongle and the Bluetooth/USB configuration, flash the reset firmware to all the devices first

### Overview & Usage

![keymap base](keymap-drawer/base/qwerty.svg)

To see all the layers check out the [full render](keymap-drawer/qwerty.svg).

⌨️ Keyboard Layers
| # | Layer      | Purpose                                                          |
| - | ---------- | ---------------------------------------------------------------- |
| 0 | **BASE**   | Standard typing with timeless home-row mods                      |
| 1 | **NUM**    | Combined digits + F-keys (tap for numbers, hold for functions)   |
| 2 | **NAV**    | Arrow keys, paging, TMUX navigation, mouse pointer               |
| 3 | **SYM**    | Symbols, punctuation, and a couple of helpers                    |
| 4 | **GAME**   | Gaming layer (just key-codes, no mods)                           |
| 5 | **EXTRAS** | Shortcuts, functions & snippets                                  |
| 6 | **MOUSE**  | Full mouse-key layer (pointer + wheel)                           |
| 7 | **SLOW**   | Low-speed pointer for pixel-perfect work                         |
| 8 | **SCROLL** | Vertical/Horizontal scroll layer                                 |

🏠 Home-Row Mods
| Side                | Hold = Modifier              | Tap = Letter / Key  |
| ------------------- | ---------------------------- | ------------------- |
| Left                | **Gui / Alt / Shift / Ctrl** | `A S D F`           |
| Right               | **Ctrl / Shift / Alt / Gui** | `J K L ;`           |


🔗 Combos
| Trigger Keys              | Result                                 |
| ------------------------- | -------------------------------------- |
| `K17 + K18`               | **Caps Word** (one-shot words in CAPS) |
| `K25 + K26`               | **Left Click**                         |
| `K26 + K27`               | **Middle Click**                       |
| `K27 + K28`               | **Right Click**                        |
| `K13 + K22`               | Toggle **MOUSE** layer                 |
| `K38 + K39` (thumb cluster)| Layer-swap **BASE ⇄ EXTRAS**           |


⚙️ Other Highlights
- **Timeless home row mods:** Based on [urob's](https://github.com/urob/zmk-config#timeless-homerow-mods) work and configured on the BASE layer with balanced flavor on both halves (280 ms tapping-term, and quick-tap with prior-idle tuning).
- **Thumb-scroll mode:** Hold the left-most thumb button (K36) while moving the trackball to turn motion into scroll.
- **Precision cursor mode:** Double-tap, then hold K36 to drop the pointer speed, release to return to normal speed.
- **Mouse-Click + Symbol-Layer - K37**
  - Tap: Left mouse click
  - Tap & Hold: Layer 3 (symbols) while the key is held
  - Double-Tap & Hold: holds the left mouse button
  - Tripple-Tap: Double mouse click
- **Backspace + Number-Layer - K38**
  - Tap: Backspace
  - Hold: Layer 1 (numbers) while the key is held
  - Double-Tap & Hold: Keeps Backspace held
- **Bluetooth profile quick-swap:** Jump to the EXTRAS layer and tap the dedicated BT-select keys to pair or switch among up to four saved hosts (plus BT CLR to forget all).
- **PMW3610 low power trackball sensor driver:** Provided by [badjeff](https://github.com/badjeff/zmk-pmw3610-driver)
  - Patched to remove build warnings and prevent cursor jump on wake
- **Hold-tap side-aware triggers:** Each HRM key only becomes a modifier if the opposite half is active, preventing accidental holds while one-handed.
- **Quick-tap / prior-idle:** Tuned for faster mod-vs-tap detection.
- **ZMK Studio:** Supported on BT builds for quick and easy keymap adjustments. Dongle support will come soon.


## Customize Keymaps, Layers, & Trackball

This section will help you personalize your firmware. Everything—from keys and layers to advanced trackball behaviors—can easily be customized, even if you're new to ZMK.

### Building Only Specific Keymaps or Shields

[scripts/generate_matrix.py](scripts/generate_matrix.py) discovers `.keymap` files
in `config/keymap/`. CI builds Bluetooth/USB and dongle bundles for each entrypoint,
plus one settings-reset bundle. Shared `.dtsi` files are not separate build targets.
The current workflow does not use `build.yaml` to select its matrix.

To add another layout, add its entrypoint to `config/keymap/`. Changing the formats
requires updating the matrix generator and workflow together. Do not delete shield
directories to select a build.


### Modify Key Mappings

**ZMK Studio**

[ZMK Studio](https://zmk.studio/) allows users to update functionality during runtime. It's currently only implemented on the Bluetooth builds.

To change the visual layout of the keys, the physical layout must be updated. This is the charybdis-layouts.dtsi file, which handles the actual physical positions of the keys. Though they may appear to be similar, this is different than the matrix transform file (charybdis.json) which handles the electrical matrix to keymap relationship.

To easily modify the physical layout, or convert a matrix transform file, [caksoylar](https://github.com/caksoylar/zmk-physical-layout-converter) has built the [ZMK physical layouts converter](https://zmk-physical-layout-converter.streamlit.app/).

For more details on how to use ZMK Studio, refer to the [ZMK documentation](https://zmk.dev/docs/features/studio).

**Keymap GUI**

Using a GUI to generate the keymap file before building the firmware is another easy way to modify the key mappings. Head over to nickcoutsos' keymap editor and follow the steps below.

- Fork/Clone this repo
- Open a new tab to the [keymap editor](https://nickcoutsos.github.io/keymap-editor/)
- Give it permission to see your repo
- Select the branch you'd like to modify
- Update the keys to match what you'd like to use on your keyboard
- Save
- Wait for the pipeline to run
- Download and flash the new firmware

**Edit Keymap Directly**

To change a key layout choose a behavior you'd like to assign to a key, then choose a parameter code. This process is more clearly outlined on ZMK's [Keymaps & Behaviors](https://zmk.dev/docs/features/keymaps) page. All keycodes are documented [here](https://zmk.dev/docs/codes) page

Edit the entrypoint and helpers under [config/keymap](config/keymap). For the
macOS/Linux pair, edit [qwerty.dtsi](config/keymap/qwerty.dtsi). Change an OS-specific
shortcut inside its conditional block, or change shared bindings below that block.
Run the keymap tests and firmware build before flashing.


### Modifying Trackball Behavior

The trackball uses ZMK's modular input processor system, making it easy to adjust pointer behavior to your liking. All trackball-related configurations and input processors are conveniently grouped in the `config/charybdis_pointer.dtsi` file. Modify this file to customize tracking speed, acceleration, scrolling behavior, and more—then rebuild your firmware.


### Building Your Customized Firmware

You can easily build your firmware locally or leverage GitHub Actions:

**Local Build (recommended for quick testing and debugging)**

Clone this repo, then run these commands from the repo root:
```sh
cd local-build
docker-compose run --rm builder
```
See the [local build README](local-build/README.md) for additional details, including how to enable USB logging in the builds.

**GitHub Actions**

- Fork or clone this repo
- Push your changes to your GitHub
- GitHub Actions automatically builds your firmware and publishes downloadable artifacts under the Actions tab.


### Troubleshooting

- If the keyboard halves aren't connecting as expected, try pressing the reset button on both halves at the same time. If that doesn't work, follow the [ZMK Connection Issues](https://zmk.dev/docs/troubleshooting/connection-issues#acquiring-a-reset-uf2) documentation for more troubleshooting steps.
- If you run into a bug or something’s not working, feel free to open an issue or submit a PR! Just keep in mind I'm not a developer, and this is a hobby project so I may not be able to fix everything.


## Credits

- [badjeff](https://github.com/badjeff)
- [eigatech](https://github.com/eigatech)
- [nickcoutsos](https://github.com/nickcoutsos/keymap-editor)
- [caksoylar](https://github.com/caksoylar/keymap-drawer)
- [urob](https://github.com/urob/zmk-config#timeless-homerow-mods)