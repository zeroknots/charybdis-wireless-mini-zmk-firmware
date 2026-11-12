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

### Build locally with Nix

The keyboard repository has its own pinned [Nix shell](flake.nix) and
[lockfile](flake.lock) for `x86_64-linux`. It does not require a NixOS rebuild,
the `devenv` CLI, Docker, root access or a persistent tool installation.
The shell provides Zephyr SDK 0.16.9 with only the ARM toolchain and the base
Python dependencies needed by the existing ZMK 0.3 / Zephyr 3.5 build.

From this repository's root:

```sh
nix develop
zmk-build                  # right/central only, normally enough for a keymap change
zmk-build --half both      # left then right, for a full update
```

Entering the shell does not build or flash anything. The first build downloads
the SDK and West sources. Later builds reuse `.build/workspace` and incremental
compilation directories. The default is two jobs. `--jobs` accepts 1 through 4.
`--pristine` asks West to rebuild the selected compilation directories.
A second command refuses to modify a workspace while a local build holds its lock.

The [builder](scripts/build.py) stages the Bluetooth/USB shields, Linux keymap and
helpers as CI does. It enables ZMK Studio only on the right/central half.
It does not run `west zephyr-export`, export CMake packages or install tools into
your home, reset settings, or flash hardware. Zephyr's compiler-probe cache stays
under `.build/cache`. Build failures stop the remaining steps.

Each successful invocation prints a new artifact directory under `.build/firmware/`.
The directory contains the selected `charybdis_left.uf2` and/or
`charybdis_right.uf2`, plus `west-manifest.yml` with the resolved source revisions.
A new directory prevents an old left image from being mixed silently with a new
right-only build. Existing artifact directories are retained.

Validate a printed directory before flashing it:

```sh
zmk-flash /path/printed/by/zmk-build --dry-run
# If you built both and intend to update both:
zmk-flash /path/printed/by/zmk-build --half both --dry-run
```

The toolchain is locked by Nix. West still follows [config/west.yml](config/west.yml),
including transitive references, as CI does. This is an incremental development
build, not a hermetic Nix firmware derivation. The saved frozen manifest records
what West resolved. Neither command updates `flake.lock` or the source manifest.

**B-key warning:** the old `v1.0.0` release predates the fix for B typing `:w`.
The current macOS and Linux sources bind B to plain `&kp B`. Use a current build,
not that old release, to get the fix. A keymap-only update normally needs the right
half only. No settings reset is required.

### Verify the firmware

1. Run `python3 -I scripts/test_keymaps.py` with Python 3 and `cpp` available.
   The tests check staged includes, shortcut positions, legacy compatibility and matrix discovery.
   They stub upstream headers and do not replace a firmware build.
2. Run `python3 -I scripts/test_flash.py` to test the helper on temporary files, without a keyboard.
3. Open this repository's [Actions page](https://github.com/zeroknots/charybdis-wireless-mini-zmk-firmware/actions/workflows/build.yml).
4. Select a successful run for the exact commit you intend to flash.
5. Download its `charybdis-qwerty-linux-bt` artifact.
6. Extract the artifact into a new directory.

### Flash with the terminal helper

Keep another keyboard available. Flashing disconnects the selected half temporarily
and replaces its firmware. Save a known-good `qwerty-bt` bundle for rollback.
Do not flash `settings_reset` or clear Bluetooth profiles for a keymap-only update.
A settings reset erases stored settings and can require pairing again.

The [right half is the central](boards/shields/charybdis_bt/charybdis_right.conf).
For keymap-only changes, ZMK normally requires flashing **right only**.
For changes that apply to both halves or ZMK split-protocol updates, flash both.
The helper's full-update sequence is left then right, not a mandated flashing order.

From the keyboard repository, show the ASCII key diagram and bootloader chords:

```sh
python3 -I scripts/flash.py --guide
```

The running keymap must match this repository for these chords to work:

- **Left:** hold A, then press Esc at the top left.
- **Right:** hold semicolon, then press backslash at the top right.

Keep both halves powered and connected to each other while using a chord.
The reset binding acts on the half where its key is pressed, not always the central.
If the chord does not work, connect the intended half by USB and double-tap its
physical reset button. This enters bootloader mode. It does not clear settings.

Validate the files and display the guide without writing anything:

```sh
python3 -I scripts/flash.py /path/to/extracted-bt-bundle --dry-run
```

Start a keymap-only update of the right half:

```sh
python3 -I scripts/flash.py /path/to/extracted-bt-bundle
```

If a full update is needed, select both halves:

```sh
python3 -I scripts/flash.py /path/to/extracted-bt-bundle --half both
```

The [helper](scripts/flash.py) checks each selected UF2 before the first write.
It rejects another MCU family, malformed blocks and writes outside the pinned
board's application partition. It never resets settings or mounts disks.

For each half, the helper asks you to connect USB and enter bootloader mode.
Mount the `NICENANO` volume in your file manager if the desktop does not do so.
The helper requires exactly one UF2 volume and a recognized nice!nano Board-ID.
If discovery is ambiguous, rerun with `--mount /run/media/YOUR_USER/NICENANO`.
It never requests root access or changes device permissions.

Before copying, type the physical half's name at the confirmation prompt.
The Board-ID identifies a compatible bootloader, **not a unique keyboard or half**.
UF2 validation cannot authenticate the source or detect a renamed wrong-half,
dongle, or settings-reset image. Use only trusted, matching Bluetooth/USB images.

The helper refuses existing destination files and symlinks. A mount change,
write failure or restart timeout stops further writes. If a copy started, a failure
can leave the result unverified. Bootloader unmount is not proof of working firmware.

After flashing, verify typing, GUI shortcuts, Foot clipboard shortcuts, Super+Space
and trackball behavior over USB. Disconnect USB and repeat over Bluetooth.
If a half does not restart or reconnect, stop before clearing settings.
To roll back, rerun the helper with the corresponding known-good `qwerty-bt` bundle.
If ZMK Studio overrides are present, inspect them before considering a settings reset.

References:

- [ZMK split keyboards](https://zmk.dev/docs/features/split-keyboards): central-only keymap updates and when to flash all parts.
- [ZMK reset behaviors](https://zmk.dev/docs/keymaps/behaviors/reset): bootloader versus restart and source-specific reset behavior.
- [nice!nano getting started](https://nicekeyboards.com/docs/nice-nano/getting-started): double-tap reset and the `NICENANO` volume.
- [ZMK connection troubleshooting](https://zmk.dev/docs/troubleshooting/connection-issues): settings-reset consequences and pairing recovery.

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