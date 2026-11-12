#!/usr/bin/env python3
"""Guide a Linux nice!nano UF2 flash without resetting settings or mounting disks.

Defaults to the right/central half for keymap-only updates. Hardware half identity
cannot be inferred from the bootloader, so every write requires an exact typed
confirmation. --dry-run and --guide never write to the keyboard.
"""

import argparse
import os
from pathlib import Path
import re
import struct
import sys
import time


GUIDE = r"""
Charybdis 3x6 - direct Bluetooth / USB (not the dongle build)

       LEFT: peripheral                         RIGHT: central / USB host
 +-----+-----+-----+-----+-----+-----+     +-----+-----+-----+-----+-----+-----+
 | Esc*|  Q  |  W  |  E  |  R  |  T  |     |  Y  |  U  |  I  |  O  |  P  |  \ *|
 +-----+-----+-----+-----+-----+-----+     +-----+-----+-----+-----+-----+-----+
 | Ctrl|  A* |  S  |  D  |  F  |  G  |     |  H  |  J  |  K  |  L  |  ;* |  '  |
 +-----+-----+-----+-----+-----+-----+     +-----+-----+-----+-----+-----+-----+
 |Shift|  Z  |  X  |  C  |  V  |  B  |     |  N  |  M  |  ,  |  .  |  /  |  /  |
 +-----+-----+-----+-----+-----+-----+     +-----+-----+-----+-----+-----+-----+
                   | Tab |Space| Bsp |     | Bsp |Enter|
                   +-----+-----+-----+     +-----+-----+

Bootloader shortcuts in this repo's qwerty / qwerty-linux keymap:
  LEFT:  hold A, then press Esc (top-left key).
  RIGHT: hold ;, then press \   (top-right key).
Keep both halves powered and connected to each other when using these chords.
If the running keymap differs, use the physical fallback instead:
  connect the selected half by USB, then double-tap its reset button.
The bootloader should appear as a mounted NICENANO USB drive.
This is bootloader mode, NOT the settings_reset firmware or Bluetooth clear.

Keymap-only update: normally flash RIGHT only (the default).
Full update: --half both guides LEFT first, then RIGHT. This is a convenient
sequence, not a ZMK-mandated order. Use matching halves from one bt bundle.
"""


class FlashError(Exception):
    """A refused or unverified operation. Stop rather than trying another disk."""


def read_firmware(path):
    """Validate a bounded nRF52840 UF2 application image before touching a disk.

    The address window comes from the pinned nice_nano.dtsi code partition.
    Reject malformed blocks, overlap, and writes to settings or bootloader areas.
    This does not authenticate the image or prove which physical half it targets.
    """
    with path.open("rb") as source:
        data = source.read(4 * 1024 * 1024 + 1)
    if not data or len(data) > 4 * 1024 * 1024 or len(data) % 512:
        raise FlashError(f"Invalid UF2 size: {path}")
    total = len(data) // 512
    ranges = []
    for index in range(total):
        offset = index * 512
        magic0, magic1, flags, address, size, number, count, family = struct.unpack_from("<8I", data, offset)
        end_magic = struct.unpack_from("<I", data, offset + 508)[0]
        if (magic0, magic1, end_magic) != (0x0A324655, 0x9E5D5157, 0x0AB16F30):
            raise FlashError(f"Invalid UF2 magic in block {index}: {path}")
        if flags != 0x2000 or family != 0xADA52840:
            raise FlashError(f"Not a normal nRF52840 application UF2: {path}")
        if number != index or count != total or not 0 < size <= 476 or size % 4:
            raise FlashError(f"Invalid UF2 block layout: {path}")
        if address % 4 or address < 0x26000 or address + size > 0xEC000:
            raise FlashError(f"UF2 writes outside the application partition: {path}")
        ranges.append((address, address + size))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise FlashError(f"UF2 blocks overlap: {path}")
    return data


def validate_mount(mount):
    """Require a real mounted nice!nano bootloader and return its device ID.

    INFO_UF2 identifies a compatible bootloader, not a unique board or half.
    Never accept an ordinary directory or mount a device with elevated privileges.
    """
    if mount.is_symlink() or not os.path.ismount(mount):
        raise FlashError(f"Not a mounted bootloader volume: {mount}")
    device = mount.stat().st_dev
    with (mount / "INFO_UF2.TXT").open(encoding="utf-8") as info:
        text = info.read(16385)
    if len(text) > 16384 or not re.search(r"^Board-ID:\s*nRF52840-nicenano\s*$", text, re.M | re.I):
        raise FlashError(f"Unrecognized nice!nano bootloader at {mount}")
    if not os.path.ismount(mount) or mount.stat().st_dev != device:
        raise FlashError("Bootloader mount changed during validation. Nothing was copied.")
    return device


def find_mount():
    """Find one bootloader among current Linux mounts. Refuse ambiguous targets."""
    candidates = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        # mountinfo escapes spaces, tabs, newlines and backslashes as octal bytes.
        path = Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4]))
        if (path / "INFO_UF2.TXT").is_file():
            candidates.append(path)
    candidates = list(dict.fromkeys(candidates))
    if len(candidates) != 1:
        raise FlashError(
            f"Found {len(candidates)} UF2 bootloader volumes. Connect one half, enter bootloader "
            "mode and mount its NICENANO drive, or pass --mount PATH. No disk was selected."
        )
    validate_mount(candidates[0])
    return candidates[0]


def copy_firmware(mount, data):
    """Create a new UF2 file on the validated mount, with no overwrite or fallback.

    A directory descriptor pins the selected filesystem during the copy. If it
    disappeared before open, refuse instead of writing into the empty mountpoint.
    A failed write can leave a partial flash. Propagate errors and stop the wizard.
    """
    device = validate_mount(mount)
    directory = os.open(mount, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if os.fstat(directory).st_dev != device:
            raise FlashError("Bootloader mount changed before the write. Nothing was copied.")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        destination = os.open("firmware.uf2", flags, 0o644, dir_fd=directory)
        with os.fdopen(destination, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(directory)


def wait_for_restart(mount, timeout=20):
    """Observe bootloader unmount, not firmware health. Timeout is not success."""
    deadline = time.monotonic() + timeout
    while os.path.ismount(mount):
        if time.monotonic() >= deadline:
            raise FlashError("Copy finished, but the bootloader did not unmount. Stop and inspect the keyboard.")
        time.sleep(0.2)


def run(args):
    """Validate all selected images, then require a physical-half confirmation per write."""
    print(GUIDE)
    if args.guide:
        return
    if args.firmware_dir is None:
        raise FlashError("Supply an extracted charybdis-qwerty-linux-bt bundle directory, or use --guide.")
    halves = ("left", "right") if args.half == "both" else (args.half,)
    # Validate BOTH files before starting the first write in a full update.
    images = {half: read_firmware(args.firmware_dir / f"charybdis_{half}.uf2") for half in halves}
    print("Validated:", ", ".join(f"{half} ({len(data)} bytes)" for half, data in images.items()))
    print("Use only trusted Bluetooth/USB images. The bootloader cannot identify left versus right.")
    if args.dry_run:
        if args.mount:
            validate_mount(args.mount)
        print("DRY RUN: no files copied, no reset, no pairing changes.")
        return
    if not sys.stdin.isatty():
        raise FlashError("Flashing requires an interactive terminal. Use --dry-run for noninteractive validation.")
    for half in halves:
        print(f"\nConnect the {half.upper()} half by USB, then enter bootloader mode (see guide above).")
        if input("Mount NICENANO, then press Enter to find it (q to cancel): ").strip():
            raise FlashError("Cancelled. No firmware was copied in this step.")
        mount = args.mount if args.mount else find_mount()
        validate_mount(mount)
        print(f"Target: {mount}\nImage: charybdis_{half}.uf2")
        if input(f"Verify the physical half. Type {half!r} to flash it: ").strip() != half:
            raise FlashError("Confirmation did not match. No firmware was copied in this step.")
        copy_firmware(mount, images[half])
        wait_for_restart(mount)
        print(f"{half.upper()}: UF2 copied and bootloader unmounted. Test the keyboard after restart.")
    print("Finished copying. Verify USB typing and trackball, then disconnect USB and verify Bluetooth.")
    print("To roll back, run this helper with the corresponding known-good bt bundle. Do not clear settings.")


def main():
    """Parse the narrow CLI and report cancellation or I/O failure without retrying writes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware_dir", type=Path, nargs="?", help="extracted matching bt bundle, not a ZIP or reset image")
    parser.add_argument("--half", choices=("right", "left", "both"), default="right", help="default: right (central, keymap-only)")
    parser.add_argument("--mount", type=Path, help="explicit mounted NICENANO volume if automatic discovery is ambiguous")
    parser.add_argument("--guide", action="store_true", help="show the ASCII bootloader guide without accessing firmware or devices")
    parser.add_argument("--dry-run", action="store_true", help="validate selected UF2 files and print the guide without flashing")
    args = parser.parse_args()
    try:
        run(args)
    except (FlashError, OSError, UnicodeError, EOFError) as error:
        print(f"Stopped: {error}\nNo further writes attempted. If a copy started, its result is unverified.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. If a copy started, its result is unverified.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
