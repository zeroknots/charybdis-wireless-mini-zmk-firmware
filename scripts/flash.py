#!/usr/bin/env python3
"""Guide a Linux nice!nano UF2 flash with USB bootloader entry and UDisks mounting.

Defaults to the right/central half for keymap-only updates. Hardware half identity
cannot be inferred from the bootloader, so every write requires an exact typed
confirmation. --dry-run and --guide never write to the keyboard.
"""

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import termios
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

USB automatic mode (after a one-time flash of USB-enabled firmware):
  Connect the requested half, confirm its name, and let the tool enter the
  bootloader and mount NICENANO. No key press is needed for subsequent flashes.
  Use --manual for the first installation or recovery. Never clear settings.

Manual bootloader shortcuts in this repo's qwerty / qwerty-linux keymap:
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


def usb_parent(device):
    """Find the physical USB parent of a sysfs tty/block device without guessing."""
    resolved = device.resolve()
    for parent in (resolved, *resolved.parents):
        if (parent / "idVendor").is_file() and (parent / "idProduct").is_file():
            return parent
    return None


def runtime_port(half, explicit=None):
    """Select exactly one matching Charybdis CDC port and its physical USB path.

    Runtime product names distinguish the peripheral from the unchanged central.
    A supplied port still has to match USB identity; it is not a validation bypass.
    """
    product = "Charybdis Left" if half == "left" else "Charybdis"
    matches = []
    for tty in Path("/sys/class/tty").glob("ttyACM*"):
        parent = usb_parent(tty / "device")
        if parent is None:
            continue
        try:
            identity = tuple((parent / key).read_text().strip() for key in ("idVendor", "idProduct", "product"))
        except OSError:
            continue  # The device may have been unplugged during discovery.
        if identity != ("1d50", "615e", product):
            continue
        port = Path("/dev") / tty.name
        if explicit is None or port.resolve() == explicit.resolve():
            matches.append((port, parent.name))
    if len(matches) > 1 or (explicit is not None and len(matches) != 1):
        raise FlashError("USB port is missing, ambiguous or not the selected Charybdis half. No reset requested.")
    return matches[0] if matches else None


def request_bootloader(port):
    """Send one 1200-baud USB touch after confirmation, without serial payload data.

    Set a normal speed first so a previous attempt cannot leave the trigger
    unchanged. Close with DTR released; firmware checks USB state and delays reset.
    Never request root, change permissions, or restore baud after a successful touch.
    """
    expected = port.stat()
    descriptor = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISCHR(opened.st_mode) or opened.st_rdev != expected.st_rdev:
            raise FlashError("Serial device changed before opening. No reset requested.")
        fcntl.ioctl(descriptor, termios.TIOCEXCL)
        attrs = termios.tcgetattr(descriptor)
        attrs[2] |= termios.CLOCAL | termios.CREAD | termios.HUPCL
        attrs[4] = attrs[5] = termios.B115200
        termios.tcsetattr(descriptor, termios.TCSANOW, attrs)
        fcntl.ioctl(descriptor, termios.TIOCMBIS, struct.pack("I", termios.TIOCM_DTR))
        attrs[4] = attrs[5] = termios.B1200
        termios.tcsetattr(descriptor, termios.TCSANOW, attrs)
        fcntl.ioctl(descriptor, termios.TIOCMBIC, struct.pack("I", termios.TIOCM_DTR))
    finally:
        os.close(descriptor)


def boot_blocks(usb_path=None):
    """Find VFAT NICENANO block devices, optionally bound to the selected USB port."""
    result = subprocess.run(
        ["lsblk", "--json", "--paths", "--output", "NAME,LABEL,FSTYPE"],
        check=True, capture_output=True, text=True,
    )
    candidates = []
    def visit(rows):
        """Walk lsblk's device/partition tree without treating names as commands."""
        for row in rows:
            if not isinstance(row, dict):
                raise FlashError("Invalid block-device metadata from lsblk.")
            name = row.get("name", "")
            if row.get("label") == "NICENANO" and row.get("fstype") in ("vfat", "fat", "msdos"):
                if not isinstance(name, str):
                    raise FlashError("Invalid NICENANO block-device name.")
                block = Path(name)
                if block.parent != Path("/dev"):
                    raise FlashError("Unexpected block-device path from lsblk.")
                parent = usb_parent(Path("/sys/class/block") / block.name)
                if parent is not None and (usb_path is None or parent.name == usb_path):
                    candidates.append(block)
            children = row.get("children")
            if children is not None and not isinstance(children, list):
                raise FlashError("Invalid block-device partition metadata.")
            visit(children or [])
    payload = json.loads(result.stdout)
    if not isinstance(payload, dict) or not isinstance(payload.get("blockdevices"), list):
        raise FlashError("Invalid block-device list from lsblk.")
    visit(payload["blockdevices"])
    if len(candidates) > 1:
        raise FlashError("Multiple NICENANO volumes match. Disconnect the other half; no disk was mounted.")
    return candidates[0] if candidates else None


def mounted_block(block):
    """Map the exact block device's major/minor ID to its mounted filesystem."""
    identity = block.stat()
    if not stat.S_ISBLK(identity.st_mode):
        raise FlashError("NICENANO candidate is no longer a block device.")
    expected = f"{os.major(identity.st_rdev)}:{os.minor(identity.st_rdev)}"
    matches = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[2] == expected:
            matches.append(Path(re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), fields[4])))
    if len(matches) > 1:
        raise FlashError("The NICENANO block device has multiple mounts. Nothing copied.")
    return matches[0] if matches else None


def ensure_boot_mount(usb_path=None, timeout=20):
    """Wait for the selected bootloader and mount it with ordinary UDisks policy.

    Mounting may require the caller's normal desktop authorization. A denied
    request is an error, never a reason to run sudo or change device permissions.
    """
    deadline = time.monotonic() + timeout
    attempted = None
    while time.monotonic() < deadline:
        block = boot_blocks(usb_path)
        if block is not None:
            mount = mounted_block(block)
            if mount is not None:
                validate_mount(mount)
                return mount
            if attempted != block:
                print(f"Mounting {block} with UDisks…")
                result = subprocess.run(
                    ["udisksctl", "mount", "--block-device", str(block)],
                    capture_output=True, text=True, timeout=30,
                )
                attempted = block
                # The desktop may have automounted it while the request ran.
                mount = mounted_block(block)
                if mount is not None:
                    validate_mount(mount)
                    return mount
                if result.returncode:
                    raise FlashError(
                        "UDisks could not mount NICENANO under this account's policy. "
                        "Run the flasher from the logged-in desktop account with access to the images. "
                        "No sudo or permission changes were attempted. " + result.stderr.strip()
                    )
        time.sleep(0.25)
    raise FlashError(
        "NICENANO did not appear. For the one-time installation or recovery, "
        "rerun with --manual and use the displayed bootloader chord. Nothing copied."
    )


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
        print(f"\nConnect the {half.upper()} half by USB. Disconnect the other USB cable before continuing.")
        manual = getattr(args, "manual", False) or args.mount is not None
        if manual:
            print("Use the bootloader chord or double-tap reset for this one-time installation/recovery.")
            if input("Enter bootloader mode, then press Enter (q to cancel): ").strip():
                raise FlashError("Cancelled. No firmware was copied in this step.")
            mount = args.mount if args.mount else ensure_boot_mount()
            validate_mount(mount)
            print(f"Target: {mount}\nImage: charybdis_{half}.uf2")
            if input(f"Verify the physical half. Type {half!r} to flash it: ").strip() != half:
                raise FlashError("Confirmation did not match. No firmware was copied in this step.")
        else:
            if input("Press Enter when the selected half is connected (q to cancel): ").strip():
                raise FlashError("Cancelled. No reset or write requested in this step.")
            candidate = runtime_port(half, getattr(args, "port", None))
            if candidate is None:
                print("No runtime USB control port found. The first installation may need manual bootloader entry.")
                if boot_blocks() is None and input("Use the displayed bootloader chord, then press Enter (q to cancel): ").strip():
                    raise FlashError("Cancelled. No firmware was copied in this step.")
                mount = ensure_boot_mount()
                print(f"Target: {mount}\nImage: charybdis_{half}.uf2")
                if input(f"Verify the physical half. Type {half!r} to flash it: ").strip() != half:
                    raise FlashError("Confirmation did not match. No firmware was copied in this step.")
            else:
                port, usb_path = candidate
                print(f"USB control: {port}\nImage: charybdis_{half}.uf2\nClose ZMK Studio or other serial clients first.")
                if input(f"Type {half!r} to request bootloader mode and flash this half: ").strip() != half:
                    raise FlashError("Confirmation did not match. No reset or write requested in this step.")
                if runtime_port(half, port) != candidate:
                    raise FlashError("USB identity changed before reset. Nothing copied.")
                request_bootloader(port)
                mount = ensure_boot_mount(usb_path)
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
    parser.add_argument("--manual", action="store_true", help="use the manual bootloader chord for initial installation or recovery; mounting remains automatic")
    parser.add_argument("--port", type=Path, help="select an exact Charybdis runtime CDC port if more than one is present")
    parser.add_argument("--guide", action="store_true", help="show the ASCII bootloader guide without accessing firmware or devices")
    parser.add_argument("--dry-run", action="store_true", help="validate selected UF2 files and print the guide without flashing")
    args = parser.parse_args()
    if args.port is not None and (args.manual or args.mount is not None):
        parser.error("--port cannot be combined with --manual or --mount")
    try:
        run(args)
    except (FlashError, OSError, UnicodeError, EOFError, ValueError, subprocess.SubprocessError) as error:
        print(f"Stopped: {error}\nNo further writes attempted. If a copy started, its result is unverified.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nCancelled. If a copy started, its result is unverified.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
