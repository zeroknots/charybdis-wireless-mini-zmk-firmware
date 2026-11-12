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

### Keep downloads small and clean old workspaces

The manifest imports only the Nordic keyboard dependencies. New fetches use shallow
history. LVGL remains a source dependency because pinned ZMK 0.3 references its
Kconfig symbols even with displays disabled. Other vendors' HALs are not needed.

To preview downloads that can be removed from an older workspace:

```sh
zmk-clean
```

To apply that preview when no build is running:

```sh
zmk-clean --apply
```

Cleanup removes only unused downloaded clones under `.build/workspace/modules`.
It refuses symlinks, path escapes, dirty clones, additional Git refs, stashes,
linked worktrees, changed revisions, recoverable detached user commits and an
active build lock. It preserves firmware bundles, compiler caches, source files
and the shared Nix store. It does not cancel or relocate a build.

### Verify the firmware

1. Run `nix build .#checks.x86_64-linux.keyboard --no-link` from the repository root.
   This checks keymaps, build orchestration, cleanup, UF2 validation, USB discovery,
   reset consent, mounting and the firmware callback's failure conditions.
   The tests use temporary files and simulated devices. They do not replace an
   ARM firmware build or physical USB testing.
2. Run `zmk-build --half both` in the Nix shell to compile both halves locally.

Alternatively, download CI-built firmware:

1. Open this repository's [Actions page](https://github.com/zeroknots/charybdis-wireless-mini-zmk-firmware/actions/workflows/build.yml).
2. Select a successful run for the exact commit you intend to flash.
3. Download its `charybdis-qwerty-linux-bt` artifact.
4. Extract the artifact into a new directory.

### Flash with the terminal helper

Keep another keyboard available. Flashing disconnects the selected half temporarily
and replaces its firmware. Save a known-good Bluetooth/USB bundle for rollback.
Do not flash `settings_reset` or clear Bluetooth profiles for this upgrade.
A settings reset erases stored settings and can require pairing again.

The [right half is the central](boards/shields/charybdis_bt/charybdis_right.conf).
Ordinary keymap-only updates normally need **right only**, which is the default.
Installing USB-triggered bootloader support requires updating **both halves once**.
The left-then-right sequence is a convenient guide, not a mandated flashing order.

#### First installation: one manual bootloader entry per half

1. Enter the project's shell with `nix develop`.
2. Run `zmk-build --half both`.
3. Save the printed artifact directory.
4. Run `zmk-flash /printed/artifact/directory --half both --dry-run`.
5. Run `zmk-flash /printed/artifact/directory --half both --manual`.

The wizard first asks you to connect the left half by USB. Use its manual shortcut,
then press Enter in the wizard. The tool mounts `NICENANO` through UDisks, asks you
to type `left`, copies the matching file and waits for the bootloader to unmount.
It then guides you through the same steps for the right half. Do not use an old
bundle for this step, because it does not contain the USB-trigger feature.

Show the full ASCII guide at any time:

```sh
zmk-flash --guide
```

Manual bootloader shortcuts in the current macOS/Linux keymaps:

- **Left:** hold A, then press Esc at the top left.
- **Right:** hold semicolon, then press backslash at the top right.

Keep both halves powered and connected to each other while using a chord.
If the running keymap differs or the chord fails, double-tap that half's physical
reset button with its USB cable connected. This enters bootloader mode without
clearing settings. Keep these manual methods available for recovery.

#### Subsequent updates: USB-triggered bootloader entry

For the normal right-half update:

```sh
zmk-flash /printed/artifact/directory
```

For both halves:

```sh
zmk-flash /printed/artifact/directory --half both
```

For each half, the wizard asks you to connect USB and type the half's name before
requesting a reboot or copying firmware. It finds the matching Charybdis CDC port,
sends a 1200-baud touch, waits for the bootloader on that physical USB port, mounts
`NICENANO` if needed and copies the validated UF2. No key press is needed after the
initial installation. Close ZMK Studio and other serial clients before starting.

The [firmware module](config/usb_flash/usb_flash.c) uses Zephyr's native CDC callback.
It does not poll in the background or replace Studio's receive callback. The reboot
requires an explicit baud-rate change to 1200, closed DTR and a configured USB link.
Normal USB connection, other baud rates and Bluetooth traffic do not trigger it.
Any process with access to the USB serial port can make this request. Do not open
the port at 1200 baud for unrelated serial work.

The left half gains a control-only CDC interface named `Charybdis Left`. It remains
the peripheral, not a second host-facing keyboard. The right half keeps the existing
`Charybdis` product name and Studio interface, preserving its pointer names.

If the old firmware has no control port, the wizard displays the manual fallback.
If a reset request produces no matching bootloader, it stops without copying.
Use `--manual` for the initial installation or recovery. `--port /dev/ttyACM0` can
select one validated runtime port when several are connected. It cannot be mixed
with `--manual` or `--mount`.

#### Accounts, mounting and safety

Automatic mounting uses the host's existing UDisks service and authorization policy.
Run the flasher as an account that can access both the UF2 files and the USB serial
port. A logged-in desktop account normally has the relevant mount authorization.
Building as `neo` does not grant that isolated account desktop USB or mount access.
The tool stops on denied access. It never invokes sudo, changes ownership or grants
permissions to bypass isolation.

A desktop account can load only the flasher, without the compiler SDK or a local
Git ownership exception, using the published flake app after this change is merged:

```sh
nix run github:zeroknots/charybdis-wireless-mini-zmk-firmware#flash -- /accessible/firmware/directory
```

The caller must already have access to the selected images. Do not weaken account
boundaries to obtain access. The normal UDisks authorization may show a desktop
approval prompt. If the desktop already mounted the exact device, the tool reuses
that mount instead of mounting it again.

The [helper](scripts/flash.py) validates all selected UF2 files before requesting a
reset or write. It rejects another MCU family, malformed blocks and writes outside
the pinned application partition. USB automatic mode tracks the selected physical
port through re-enumeration, so another keyboard's bootloader is not a substitute.
Manual mode requires one unambiguous NICENANO volume or an explicit existing
`--mount` path, followed by validation of the nice!nano Board-ID.

The Board-ID alone cannot identify a unique keyboard or half. UF2 validation cannot
authenticate the source or detect a renamed wrong-half, dongle or settings-reset
image. Use trusted matching Bluetooth/USB images and verify the connected half.

Existing destination files, symlinks, mount changes, failed copies and restart
timeouts stop further writes. If a copy started, its result can remain unverified.
Bootloader unmount is not proof of healthy firmware. After flashing, verify typing,
B, held T, clipboard shortcuts and the trackball over USB, then over Bluetooth.

To roll back, run the helper with the corresponding known-good bundle. An older
image can remove USB-trigger support, so manual bootloader entry remains necessary
for recovery. Inspect any ZMK Studio overrides before considering a settings reset.

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