#!/usr/bin/env python3
"""Test local-build orchestration using fake West steps and temporary files only."""

import contextlib
import fcntl
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location("charybdis_build", ROOT / "scripts/build.py")
BUILD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILD)


class BuildTests(unittest.TestCase):
    """Protect target selection, staging, bounded jobs and failure propagation."""

    def setUp(self):
        """Create a minimal source tree without downloading or compiling anything."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.commands = []
        files = {
            "config/west.yml": "manifest: {}\n",
            "config/keymap/qwerty-linux.keymap": '#define CHARYBDIS_LINUX\n#include "qwerty.dtsi"\n',
            "config/keymap/qwerty.dtsi": "shared keymap",
            "config/keymap/behaviors.dtsi": "keymap helper",
            "config/charybdis-layouts.dtsi": "layout",
            "config/charybdis_pmw3610.dtsi": "sensor",
            "config/charybdis_pointer.dtsi": "pointer",
            "boards/shields/charybdis_bt/charybdis_right.conf": "CONFIG_ZMK_SPLIT_ROLE_CENTRAL=y\n",
            "boards/shields/charybdis_bt/charybdis_left.conf": "CONFIG_ZMK_SPLIT_ROLE_CENTRAL=n\n",
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.env = mock.patch.dict(os.environ, ZEPHYR_SDK_INSTALL_DIR="/fake-sdk")
        self.env.start()
        self.addCleanup(self.env.stop)
        self.which = mock.patch.object(BUILD.shutil, "which", return_value="/fake-tool")
        self.which.start()
        self.addCleanup(self.which.stop)

    def fake_command(self, args, cwd, env):
        """Emulate only West's expected build products and record every invocation."""
        args = list(map(str, args))
        self.commands.append(args)
        self.assertEqual(env["ZEPHYR_BASE"], str(cwd / "zephyr"))
        if args[:2] == ["west", "init"]:
            (cwd / ".west").mkdir()
        if args[:2] == ["west", "build"]:
            image = Path(args[args.index("-d") + 1]) / "zephyr/zmk.uf2"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(b"fake image")

    def run_build(self, half="right", jobs=2, pristine=False):
        """Replace West execution while exercising the actual filesystem staging."""
        with mock.patch.object(BUILD, "command", side_effect=self.fake_command), \
                mock.patch.object(BUILD.subprocess, "run", return_value=SimpleNamespace(stdout="frozen manifest\n")), \
                contextlib.redirect_stdout(io.StringIO()):
            return BUILD.build(self.root, half, jobs, pristine)

    def test_manifest_records_only_updated_active_projects(self):
        """West update skips inactive projects, so freezing them must not break a build."""
        with mock.patch.object(BUILD, "command", side_effect=self.fake_command), \
                mock.patch.object(BUILD.subprocess, "run", return_value=SimpleNamespace(stdout="active manifest\n")) as freeze, \
                contextlib.redirect_stdout(io.StringIO()):
            output = BUILD.build(self.root, "right", 2, False)
            self.assertEqual((output / "west-manifest.yml").read_text(), "active manifest\n")
            self.assertIn("--active-only", freeze.call_args.args[0], "inactive, uncloned projects must not be frozen")

    def test_west_uses_the_complete_shell_python(self):
        """Do not use the standalone West wrapper that hides Studio dependencies."""
        env = {"PATH": "/project/python/bin"}
        with mock.patch.object(BUILD.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
            BUILD.command(["west", "update", "--narrow"], self.root, env)
            run.assert_called_once_with(
                [BUILD.sys.executable, "-I", "-m", "west", "update", "--narrow"],
                cwd=self.root, env=env, check=True,
            )

    def test_right_only_and_bluetooth_usb_flags(self):
        """Default update targets only right, uses Linux keymap and enables Studio."""
        output = self.run_build()
        builds = [args for args in self.commands if args[:2] == ["west", "build"]]
        self.assertEqual(len(builds), 1)
        args = builds[0]
        self.assertIn("-DSHIELD=charybdis_right", args)
        self.assertIn("nice_nano_v2", args)
        self.assertIn("-DSNIPPET=studio-rpc-usb-uart", args)
        self.assertIn("--build-opt=-j2", args)
        self.assertIn("-DKEYMAP_FILE=overlays/charybdis.keymap", args)
        self.assertIn("-DCMAKE_POLICY_VERSION_MINIMUM=3.5", args)
        self.assertIn(f"-DPython3_EXECUTABLE={BUILD.sys.executable}", args)
        self.assertIn(f"-DUSER_CACHE_DIR={self.root / '.build/cache'}", args)
        self.assertEqual(sorted(path.name for path in output.iterdir()), ["charybdis_right.uf2", "west-manifest.yml"])
        workspace = self.root / ".build/workspace"
        self.assertEqual((workspace / "zmk/app/overlays/qwerty.dtsi").read_text(), "shared keymap")
        self.assertEqual((workspace / "zmk/app/overlays/charybdis.keymap").read_text(), (self.root / "config/keymap/qwerty-linux.keymap").read_text())
        self.assertTrue((workspace / "zmk/app/boards/shields/charybdis_bt/charybdis_pointer.dtsi").is_file())
        self.assertFalse(any("zephyr-export" in args or "flash" in args for args in self.commands))

    def test_both_is_sequential_and_snippet_is_central_only(self):
        """Both mode builds left then right without applying Studio to the peripheral."""
        output = self.run_build("both", jobs=4, pristine=True)
        builds = [args for args in self.commands if args[:2] == ["west", "build"]]
        self.assertEqual(len(builds), 2)
        self.assertIn("-DSHIELD=charybdis_left", builds[0])
        self.assertNotIn("-DSNIPPET=studio-rpc-usb-uart", builds[0])
        self.assertIn("-DSHIELD=charybdis_right", builds[1])
        self.assertIn("-DSNIPPET=studio-rpc-usb-uart", builds[1])
        for args in builds:
            self.assertIn("--build-opt=-j4", args)
            self.assertEqual(args[args.index("-p") + 1], "always")
        self.assertTrue((output / "charybdis_left.uf2").is_file())
        self.assertTrue((output / "charybdis_right.uf2").is_file())

    def test_incremental_workspace_and_fresh_output_bundles(self):
        """Reuse compilation, not stale firmware from a different build invocation."""
        first = self.run_build("both")
        self.commands.clear()
        second = self.run_build("right")
        self.assertNotEqual(first, second)
        self.assertTrue((first / "charybdis_left.uf2").exists())
        self.assertFalse((second / "charybdis_left.uf2").exists())
        self.assertFalse(any(args[:2] == ["west", "init"] for args in self.commands))
        self.assertIn(["west", "update", "--narrow", "--fetch-opt=--depth=1"], self.commands)

    def test_invalid_jobs_or_source_tree_do_not_run_west(self):
        """Reject resource-limit bypasses and accidental use from another repository."""
        for jobs in (-1, 0, 5, 1000):
            with self.subTest(jobs=jobs), mock.patch.object(BUILD, "command") as command:
                with self.assertRaises(BUILD.BuildError):
                    BUILD.build(self.root, "right", jobs, False)
                command.assert_not_called()
        (self.root / "config/west.yml").unlink()
        with self.assertRaises(BUILD.BuildError):
            self.run_build()

    def test_missing_sdk_or_command_is_actionable_failure(self):
        """Never substitute system compilers or install missing dependencies."""
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(BUILD.BuildError):
                self.run_build()
        with mock.patch.object(BUILD.shutil, "which", return_value=None):
            with self.assertRaises(BUILD.BuildError):
                self.run_build()

    def test_symlinks_are_not_deleted_or_used_as_workspace(self):
        """Generated-path handling must not recursively modify another directory."""
        other = self.root / "keep"
        other.mkdir()
        (other / "sentinel").write_text("keep")
        (self.root / ".build").symlink_to(other, target_is_directory=True)
        with self.assertRaises(BUILD.BuildError):
            self.run_build()
        self.assertEqual((other / "sentinel").read_text(), "keep")

    def test_concurrent_build_is_refused(self):
        """A second command must not restart or modify an active workspace."""
        generated = self.root / ".build"
        generated.mkdir()
        with (generated / "build.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BUILD.BuildError):
                self.run_build()
        self.assertEqual(self.commands, [])

    def test_failed_update_does_not_attempt_build(self):
        """Stop immediately when sources cannot be synchronized."""
        def fail_update(args, cwd, env):
            """Permit init but reproduce an offline or rejected West update."""
            self.fake_command(args, cwd, env)
            if args[:2] == ["west", "update"]:
                raise subprocess.CalledProcessError(1, args)
        with mock.patch.object(BUILD, "command", side_effect=fail_update), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.CalledProcessError):
                BUILD.build(self.root, "both", 2, False)
        self.assertFalse(any(args[:2] == ["west", "build"] for args in self.commands))


if __name__ == "__main__":
    unittest.main()
