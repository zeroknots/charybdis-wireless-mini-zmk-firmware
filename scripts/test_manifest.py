#!/usr/bin/env python3
"""Protect the required Nordic/ZMK module set and local USB-module discovery."""
import os
from pathlib import Path
import unittest
import yaml

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))


class ManifestTests(unittest.TestCase):
    """Dependency trimming must not remove Kconfig inputs or upgrade firmware sources."""
    def test_required_modules_without_other_vendor_hals(self):
        """LVGL is a Kconfig dependency of pinned ZMK even when no display is built."""
        manifest = yaml.safe_load((ROOT / "config/west.yml").read_text())["manifest"]
        zmk = next(project for project in manifest["projects"] if project["name"] == "zmk")
        self.assertEqual(zmk["import"]["file"], "app/west.yml")
        self.assertEqual(set(zmk["import"]["name-allowlist"]), {
            "zephyr", "cmsis", "hal_nordic", "segger", "lvgl", "tinycrypt",
            "nanopb", "zmk-studio-messages",
        })
        self.assertEqual(zmk["revision"], "edf5c0814fd3ea202e43aad2d68fd32e882a518c")
        self.assertEqual(zmk["clone-depth"], 1)
        driver = next(project for project in manifest["projects"] if project["name"] == "zmk-pmw3610-driver")
        self.assertEqual(driver["revision"], "14d39b7a6944d1014544a2382707b14724c22f49")

    def test_local_module_and_both_halves_are_wired(self):
        """The manifest project's module is discoverable by local and existing CI builds."""
        module = yaml.safe_load((ROOT / "config/zephyr/module.yml").read_text())
        self.assertTrue((ROOT / "config" / module["build"]["cmake"] / "CMakeLists.txt").is_file())
        self.assertTrue((ROOT / "config" / module["build"]["kconfig"]).is_file())
        for half in ("left", "right"):
            with self.subTest(half=half):
                text = (ROOT / f"boards/shields/charybdis_bt/charybdis_{half}.conf").read_text()
                self.assertIn("CONFIG_CHARYBDIS_USB_FLASH=y", text)


if __name__ == "__main__":
    unittest.main()
