#!/usr/bin/env python3
"""Test USB discovery, reset consent and automatic mounting without real devices."""
import argparse
import contextlib
import io
import os
from pathlib import Path
import runpy
import stat
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))
FIXTURE = runpy.run_path(str(ROOT / "scripts/test_flash.py"))
FLASH, uf2 = FIXTURE["FLASH"], FIXTURE["uf2"]


class UsbHostTests(unittest.TestCase):
    """No USB reset, mount or firmware copy may happen without a validated target."""
    def setUp(self):
        """Build fake sysfs metadata and valid source images in a disposable directory."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for half in ("left", "right"):
            (self.root / f"charybdis_{half}.uf2").write_bytes(uf2())
        self.usb = self.root / "usb/1-2"
        self.usb.mkdir(parents=True)
        for key, value in (("idVendor", "1d50"), ("idProduct", "615e"), ("product", "Charybdis")):
            (self.usb / key).write_text(value)
        interface = self.usb / "1-2:1.0"
        interface.mkdir()
        self.tty = self.root / "ttyACM0"
        self.tty.mkdir()
        (self.tty / "device").symlink_to(interface, target_is_directory=True)
        self.mount = self.root / "NICENANO"
        self.args = argparse.Namespace(firmware_dir=self.root, half="right", mount=None,
                                       guide=False, dry_run=False, manual=False, port=None)

    def test_runtime_identity_and_half_selection(self):
        """Select exact runtime IDs/products, not arbitrary serial ports or other halves."""
        with mock.patch.object(Path, "glob", return_value=[self.tty]):
            self.assertEqual(FLASH.runtime_port("right"), (Path("/dev/ttyACM0"), "1-2"))
            self.assertIsNone(FLASH.runtime_port("left"))
            (self.usb / "product").write_text("Charybdis Left")
            self.assertEqual(FLASH.runtime_port("left"), (Path("/dev/ttyACM0"), "1-2"))
            self.assertIsNone(FLASH.runtime_port("right"))
            (self.usb / "idVendor").write_text("ffff")
            self.assertIsNone(FLASH.runtime_port("left"))
            with self.assertRaises(FLASH.FlashError):
                FLASH.runtime_port("left", Path("/dev/ttyACM0"))

    def test_ambiguous_runtime_ports_are_refused(self):
        """Never pick an arbitrary device when two same-half controllers are connected."""
        second = self.root / "ttyACM1"
        second.mkdir()
        (second / "device").symlink_to(self.usb / "1-2:1.0", target_is_directory=True)
        with mock.patch.object(Path, "glob", return_value=[self.tty, second]):
            with self.assertRaises(FLASH.FlashError):
                FLASH.runtime_port("right")
            self.assertEqual(FLASH.runtime_port("right", Path("/dev/ttyACM1"))[0], Path("/dev/ttyACM1"))

    def test_touch_is_115200_then_1200_and_closes_without_payload(self):
        """Use line control only, with DTR released and the descriptor always closed."""
        identity = SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=os.makedev(166, 0))
        speeds = []
        def set_speed(fd, when, attrs):
            """Capture speeds by value before the mutable termios list changes again."""
            del fd, when
            speeds.append((attrs[4], attrs[5]))
        with mock.patch.object(Path, "stat", return_value=identity), \
                mock.patch.object(FLASH.os, "open", return_value=10), \
                mock.patch.object(FLASH.os, "fstat", return_value=identity), \
                mock.patch.object(FLASH.os, "close") as close, \
                mock.patch.object(FLASH.os, "write") as write, \
                mock.patch.object(FLASH.fcntl, "ioctl") as ioctl, \
                mock.patch.object(FLASH.termios, "tcgetattr", return_value=[0, 0, 0, 0, 0, 0, []]), \
                mock.patch.object(FLASH.termios, "tcsetattr", side_effect=set_speed):
            FLASH.request_bootloader(Path("/dev/ttyACM0"))
            self.assertEqual(speeds, [(FLASH.termios.B115200,) * 2, (FLASH.termios.B1200,) * 2])
            self.assertEqual([call.args[1] for call in ioctl.call_args_list],
                             [FLASH.termios.TIOCEXCL, FLASH.termios.TIOCMBIS, FLASH.termios.TIOCMBIC])
            close.assert_called_once_with(10)
            write.assert_not_called()

    def test_device_change_refuses_touch_but_closes_descriptor(self):
        """Do not send control requests if the opened node has another device number."""
        with mock.patch.object(Path, "stat", return_value=SimpleNamespace(st_rdev=1)), \
                mock.patch.object(FLASH.os, "open", return_value=10), \
                mock.patch.object(FLASH.os, "fstat", return_value=SimpleNamespace(st_mode=stat.S_IFCHR, st_rdev=2)), \
                mock.patch.object(FLASH.os, "close") as close, \
                mock.patch.object(FLASH.termios, "tcsetattr") as settings:
            with self.assertRaises(FLASH.FlashError):
                FLASH.request_bootloader(Path("/dev/ttyACM0"))
            settings.assert_not_called()
            close.assert_called_once_with(10)

    def test_usb_path_filters_boot_volumes_and_rejects_ambiguity(self):
        """A different keyboard's NICENANO drive must not be selected after reset."""
        rows = {"blockdevices": [
            {"name": "/dev/sda", "label": "NICENANO", "fstype": "vfat"},
            {"name": "/dev/sdb", "label": "NICENANO", "fstype": "vfat"},
            {"name": "/dev/sdc", "label": "OTHER", "fstype": "vfat"},
        ]}
        import json
        with mock.patch.object(FLASH.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(rows))), \
                mock.patch.object(FLASH, "usb_parent", side_effect=lambda path: SimpleNamespace(name="1-2" if path.name == "sda" else "1-3")):
            self.assertEqual(FLASH.boot_blocks("1-2"), Path("/dev/sda"))
            with self.assertRaises(FLASH.FlashError):
                FLASH.boot_blocks()

    def test_foreign_or_malformed_boot_devices_are_never_selected(self):
        """One foreign volume is not a fallback; malformed JSON shape fails closed."""
        import json
        foreign = {"blockdevices": [{"name": "/dev/sdb", "label": "NICENANO", "fstype": "vfat", "children": None}]}
        with mock.patch.object(FLASH.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(foreign))), \
                mock.patch.object(FLASH, "usb_parent", return_value=SimpleNamespace(name="1-3")):
            self.assertIsNone(FLASH.boot_blocks("1-2"))
        for payload in ([], {}, {"blockdevices": None}, {"blockdevices": ["not a device"]},
                        {"blockdevices": [{"name": None, "label": "NICENANO", "fstype": "vfat"}]},
                        {"blockdevices": [{"name": "/dev/sda", "children": "not a list"}]}):
            with self.subTest(payload=payload), \
                    mock.patch.object(FLASH.subprocess, "run", return_value=SimpleNamespace(stdout=json.dumps(payload))):
                with self.assertRaises(FLASH.FlashError):
                    FLASH.boot_blocks("1-2")

    def test_automatic_mount_uses_only_ordinary_udisks(self):
        """Mount the exact discovered block, never sudo or a permissions workaround."""
        block = Path("/dev/sda")
        with mock.patch.object(FLASH, "boot_blocks", return_value=block) as discover, \
                mock.patch.object(FLASH, "mounted_block", side_effect=[None, self.mount]), \
                mock.patch.object(FLASH, "validate_mount"), \
                mock.patch.object(FLASH.subprocess, "run", return_value=SimpleNamespace(returncode=0, stderr="")) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(FLASH.ensure_boot_mount("1-2"), self.mount)
            discover.assert_called_once_with("1-2")
            self.assertEqual(run.call_args.args[0], ["udisksctl", "mount", "--block-device", "/dev/sda"])

    def test_existing_mount_avoids_second_mount_and_denial_stops(self):
        """Desktop automount is reused; a policy denial is surfaced without escalation."""
        with mock.patch.object(FLASH, "boot_blocks", return_value=Path("/dev/sda")), \
                mock.patch.object(FLASH, "mounted_block", return_value=self.mount), \
                mock.patch.object(FLASH, "validate_mount"), mock.patch.object(FLASH.subprocess, "run") as run:
            self.assertEqual(FLASH.ensure_boot_mount("1-2"), self.mount)
            run.assert_not_called()
        with mock.patch.object(FLASH, "boot_blocks", return_value=Path("/dev/sda")), \
                mock.patch.object(FLASH, "mounted_block", return_value=None), \
                mock.patch.object(FLASH.subprocess, "run", return_value=SimpleNamespace(returncode=1, stderr="not authorized")) as run, \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(FLASH.FlashError, "account's policy"):
                FLASH.ensure_boot_mount("1-2")
            self.assertEqual(run.call_count, 1)

    def test_reset_requires_confirmation_and_precedes_mount_and_write(self):
        """Wrong consent cannot reset; valid consent keeps reset, mount, copy ordered."""
        for answer in ("left", "right"):
            events = []
            with self.subTest(answer=answer), \
                    mock.patch.object(FLASH.sys.stdin, "isatty", return_value=True), \
                    mock.patch("builtins.input", side_effect=["", answer]), \
                    mock.patch.object(FLASH, "runtime_port", return_value=(Path("/dev/ttyACM0"), "1-2")), \
                    mock.patch.object(FLASH, "request_bootloader", side_effect=lambda port: events.append("reset")), \
                    mock.patch.object(FLASH, "ensure_boot_mount", side_effect=lambda port: (events.append("mount"), self.mount)[1]), \
                    mock.patch.object(FLASH, "copy_firmware", side_effect=lambda path, data: events.append("copy")), \
                    mock.patch.object(FLASH, "wait_for_restart", side_effect=lambda path: events.append("restart")), \
                    contextlib.redirect_stdout(io.StringIO()):
                if answer == "left":
                    with self.assertRaises(FLASH.FlashError):
                        FLASH.run(self.args)
                    self.assertEqual(events, [])
                else:
                    FLASH.run(self.args)
                    self.assertEqual(events, ["reset", "mount", "copy", "restart"])

    def test_dry_run_never_probes_resets_or_mounts_usb(self):
        """A valid firmware preview is read-only even with automatic mode selected."""
        self.args.dry_run = True
        with mock.patch.object(FLASH, "runtime_port") as discover, \
                mock.patch.object(FLASH, "request_bootloader") as reset, \
                mock.patch.object(FLASH, "ensure_boot_mount") as mount, contextlib.redirect_stdout(io.StringIO()):
            FLASH.run(self.args)
            discover.assert_not_called()
            reset.assert_not_called()
            mount.assert_not_called()

    def test_both_halves_are_guided_and_correlated_independently(self):
        """Left and right must each be confirmed and mapped to their own USB port."""
        self.args.half = "both"
        left, right = (Path("/dev/ttyACM0"), "1-2"), (Path("/dev/ttyACM1"), "1-3")
        with mock.patch.object(FLASH.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", side_effect=["", "left", "", "right"]), \
                mock.patch.object(FLASH, "runtime_port", side_effect=[left, left, right, right]), \
                mock.patch.object(FLASH, "request_bootloader") as reset, \
                mock.patch.object(FLASH, "ensure_boot_mount", return_value=self.mount) as mount, \
                mock.patch.object(FLASH, "copy_firmware") as copy, \
                mock.patch.object(FLASH, "wait_for_restart"), contextlib.redirect_stdout(io.StringIO()):
            FLASH.run(self.args)
            self.assertEqual([call.args[0] for call in reset.call_args_list], [left[0], right[0]])
            self.assertEqual([call.args[0] for call in mount.call_args_list], ["1-2", "1-3"])
            self.assertEqual(copy.call_count, 2)

    def test_conflicting_target_options_are_rejected_before_device_access(self):
        """Do not silently ignore a serial target when a manual mount was specified."""
        for options in (("--manual",), ("--mount", str(self.mount))):
            result = subprocess.run(
                [FLASH.sys.executable, "-I", str(ROOT / "scripts/flash.py"), str(self.root),
                 "--port", "/dev/ttyACM0", *options], capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot be combined", result.stderr)

    def test_timeout_never_selects_some_other_volume(self):
        """No matching re-enumeration is an error, not permission to flash another disk."""
        with mock.patch.object(FLASH.time, "monotonic", side_effect=[0, 21]), \
                mock.patch.object(FLASH, "boot_blocks") as blocks:
            with self.assertRaisesRegex(FLASH.FlashError, "one-time installation"):
                FLASH.ensure_boot_mount("1-2")
            blocks.assert_not_called()


if __name__ == "__main__":
    unittest.main()
