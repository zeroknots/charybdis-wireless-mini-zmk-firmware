#!/usr/bin/env python3
"""Exercise flashing safety on temporary files only. No keyboard is accessed.

CHARYBDIS_TEST_ROOT selects a disposable checkout for deliberate-defect probes.
All successful-copy tests replace mount validation with a temporary directory.
"""

import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location("charybdis_flash", ROOT / "scripts/flash.py")
FLASH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FLASH)


def uf2(**changes):
    """Make one synthetic UF2 block with independently specified header fields."""
    fields = dict(magic0=0x0A324655, magic1=0x9E5D5157, flags=0x2000,
                  address=0x26000, size=256, number=0, count=1, family=0xADA52840)
    fields.update(changes)
    block = bytearray(512)
    struct.pack_into("<8I", block, 0, *fields.values())
    struct.pack_into("<I", block, 508, 0x0AB16F30)
    return bytes(block)


class FlashTests(unittest.TestCase):
    """Reject invalid sources, ambiguous disks, missing consent and failed writes."""

    def setUp(self):
        """Create disposable source and target directories, never actual mounts."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.mount = self.root / "NICENANO with spaces"
        self.mount.mkdir()
        (self.mount / "INFO_UF2.TXT").write_text("UF2 Bootloader\nBoard-ID: nRF52840-nicenano\n")
        self.firmware = self.root / "charybdis_right.uf2"
        self.firmware.write_bytes(uf2())
        (self.root / "charybdis_left.uf2").write_bytes(uf2())
        self.args = argparse.Namespace(firmware_dir=self.root, half="right", mount=self.mount,
                                       guide=False, dry_run=False)

    def test_valid_image(self):
        """A normal application block must survive validation unchanged."""
        self.assertEqual(FLASH.read_firmware(self.firmware), uf2())

    def test_reject_malformed_or_wrong_target(self):
        """Do not flash other chips, bootloaders, settings, or incomplete blocks."""
        cases = [b"", b"not UF2", uf2()[:-1], uf2() + b"x", b"x" * (4 * 1024 * 1024 + 1)]
        cases += [uf2(**change) for change in (
            {"magic0": 0}, {"magic1": 0}, {"flags": 0}, {"flags": 0x2001},
            {"family": 0xE48BFF56}, {"count": 2}, {"number": 1}, {"size": 0},
            {"size": 480}, {"size": 255}, {"address": 0x25000},
            {"address": 0xEC000}, {"address": 0xF4000}, {"address": 0x26001},
            {"address": 0xEBFFC},
        )]
        cases += [uf2()[:-4] + b"\0\0\0\0"]
        for data in cases:
            with self.subTest(size=len(data), header=data[:32]):
                self.firmware.write_bytes(data)
                with self.assertRaises(FLASH.FlashError):
                    FLASH.read_firmware(self.firmware)

    def test_reject_overlap_and_accept_partition_boundary(self):
        """Overlapping blocks fail even when their numbering and counts are valid."""
        self.firmware.write_bytes(uf2(count=2) + uf2(count=2, number=1, address=0x26080))
        with self.assertRaises(FLASH.FlashError):
            FLASH.read_firmware(self.firmware)
        data = uf2(address=0xEBF00)
        self.firmware.write_bytes(data)
        self.assertEqual(FLASH.read_firmware(self.firmware), data)

    def test_mount_identity_and_real_mount_required(self):
        """An INFO file alone must never turn an ordinary directory into a target."""
        with self.assertRaises(FLASH.FlashError):
            FLASH.validate_mount(self.mount)
        with mock.patch.object(FLASH.os.path, "ismount", return_value=True):
            self.assertEqual(FLASH.validate_mount(self.mount), self.mount.stat().st_dev)
            (self.mount / "INFO_UF2.TXT").write_text("Board-ID: some-other-board\n")
            with self.assertRaises(FLASH.FlashError):
                FLASH.validate_mount(self.mount)
            (self.mount / "INFO_UF2.TXT").write_text("Board-ID: nRF52840-nicenano\n" + "x" * 16385)
            with self.assertRaises(FLASH.FlashError):
                FLASH.validate_mount(self.mount)

    def test_symlink_mount_is_refused(self):
        """Reject a symlink even if its target is reported as mounted."""
        alias = self.root / "alias"
        alias.symlink_to(self.mount, target_is_directory=True)
        with mock.patch.object(FLASH.os.path, "ismount", return_value=True):
            with self.assertRaises(FLASH.FlashError):
                FLASH.validate_mount(alias)

    def test_discovery_handles_spaces_and_refuses_ambiguity(self):
        """Decode Linux mount escapes and require exactly one UF2 volume."""
        escaped = str(self.mount).replace(" ", r"\040")
        line = f"1 0 8:1 / {escaped} rw - vfat /dev/fake rw\n"
        with mock.patch.object(Path, "read_text", return_value=line), \
                mock.patch.object(FLASH.os.path, "ismount", return_value=True):
            self.assertEqual(FLASH.find_mount(), self.mount)
        other = self.root / "OTHER"
        other.mkdir()
        (other / "INFO_UF2.TXT").write_text("Board-ID: nRF52840-nicenano\n")
        two = line + f"2 0 8:2 / {other} rw - vfat /dev/fake2 rw\n"
        with mock.patch.object(Path, "read_text", return_value=two):
            with self.assertRaises(FLASH.FlashError):
                FLASH.find_mount()
        with mock.patch.object(Path, "read_text", return_value=""):
            with self.assertRaises(FLASH.FlashError):
                FLASH.find_mount()

    def test_copy_never_overwrites_or_follows_destination_symlink(self):
        """A successful copy is exact. Existing files and symlinks remain untouched."""
        with mock.patch.object(FLASH, "validate_mount", return_value=self.mount.stat().st_dev):
            FLASH.copy_firmware(self.mount, uf2())
            self.assertEqual((self.mount / "firmware.uf2").read_bytes(), uf2())
            with self.assertRaises(FileExistsError):
                FLASH.copy_firmware(self.mount, b"replacement")
            (self.mount / "firmware.uf2").unlink()
            victim = self.root / "keep.txt"
            victim.write_text("keep me")
            (self.mount / "firmware.uf2").symlink_to(victim)
            with self.assertRaises(OSError):
                FLASH.copy_firmware(self.mount, uf2())
            self.assertEqual(victim.read_text(), "keep me")

    def test_sync_failure_is_not_success(self):
        """Propagate a device flush failure even if the write itself returned."""
        with mock.patch.object(FLASH, "validate_mount", return_value=self.mount.stat().st_dev), \
                mock.patch.object(FLASH.os, "fsync", side_effect=OSError("device disconnected")):
            with self.assertRaises(OSError):
                FLASH.copy_firmware(self.mount, uf2())

    def test_disappeared_mount_cannot_fall_back_to_normal_directory(self):
        """A different filesystem after opening the target must prevent file creation."""
        with mock.patch.object(FLASH, "validate_mount", return_value=-1):
            with self.assertRaises(FLASH.FlashError):
                FLASH.copy_firmware(self.mount, uf2())
        self.assertFalse((self.mount / "firmware.uf2").exists())

    def test_confirmation_and_interactive_terminal_are_required(self):
        """Neither piped input nor naming the wrong half authorizes a write."""
        with mock.patch.object(FLASH.sys.stdin, "isatty", return_value=False), \
                mock.patch.object(FLASH, "copy_firmware") as copy, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(FLASH.FlashError):
                FLASH.run(self.args)
            copy.assert_not_called()
        with mock.patch.object(FLASH.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=["", "left"]), \
                mock.patch.object(FLASH, "validate_mount"), \
                mock.patch.object(FLASH, "copy_firmware") as copy, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(FLASH.FlashError):
                FLASH.run(self.args)
            copy.assert_not_called()

    def test_both_validates_every_image_before_any_write(self):
        """A malformed right image must block the left flash too."""
        self.args.half = "both"
        self.firmware.write_bytes(b"invalid right half")
        with mock.patch.object(FLASH, "copy_firmware") as copy, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(FLASH.FlashError):
                FLASH.run(self.args)
            copy.assert_not_called()

    def test_full_update_order_and_stop_on_write_failure(self):
        """Both mode visits left then right, but a left write error stops the process."""
        self.args.half = "both"
        for failure in (False, True):
            answers = []
            def answer(prompt):
                """Record the half-specific consent prompts in their actual order."""
                answers.append(prompt)
                return next(responses)
            responses = iter(["", "left", "", "right"])
            with mock.patch.object(FLASH.sys.stdin, "isatty", return_value=True), \
                    mock.patch("builtins.input", side_effect=answer), \
                    mock.patch.object(FLASH, "validate_mount"), \
                    mock.patch.object(FLASH, "copy_firmware", side_effect=OSError("write failed") if failure else None) as copy, \
                    mock.patch.object(FLASH, "wait_for_restart"), contextlib.redirect_stdout(io.StringIO()):
                if failure:
                    with self.assertRaises(OSError):
                        FLASH.run(self.args)
                    self.assertEqual(copy.call_count, 1)
                    self.assertEqual(len(answers), 2)
                else:
                    FLASH.run(self.args)
                    self.assertEqual(copy.call_count, 2)
                    self.assertIn("'left'", answers[1])
                    self.assertIn("'right'", answers[3])

    def test_guide_and_dry_run_never_copy(self):
        """Read-only modes must work without a keyboard or terminal."""
        for mode in ("guide", "dry_run"):
            self.args.mount = None
            setattr(self.args, mode, True)
            with mock.patch.object(FLASH, "copy_firmware") as copy, \
                    mock.patch.object(FLASH, "find_mount") as find, contextlib.redirect_stdout(io.StringIO()):
                FLASH.run(self.args)
                copy.assert_not_called()
                find.assert_not_called()
            setattr(self.args, mode, False)

    def test_restart_timeout_is_not_success(self):
        """An unchanged bootloader mount cannot count as a verified restart."""
        with mock.patch.object(FLASH.os.path, "ismount", return_value=True), \
                mock.patch.object(FLASH.time, "monotonic", side_effect=[0, 21]):
            with self.assertRaises(FLASH.FlashError):
                FLASH.wait_for_restart(self.mount)

    def test_cli_default_is_right_and_no_input_is_an_error(self):
        """Exercise real argument parsing without any device access."""
        command = [sys.executable, "-I", str(ROOT / "scripts/flash.py")]
        valid = subprocess.run(command + [str(self.root), "--dry-run"], capture_output=True, text=True)
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertIn("Validated: right (512 bytes)", valid.stdout)
        self.assertNotIn("Validated: left", valid.stdout)
        invalid = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 1)
        self.assertFalse((self.mount / "firmware.uf2").exists())


if __name__ == "__main__":
    unittest.main()
