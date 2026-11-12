#!/usr/bin/env python3
"""Check shortcut contracts using the same keymap/helper staging as firmware CI.

Only upstream headers are stubbed. These tests check source-level bindings and
include resolution, not ZMK compilation or live HID behavior. Set
CHARYBDIS_TEST_ROOT to test a disposable mutated checkout without editing this one.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))


def preprocess(keymap):
    """Stage one entrypoint plus DTSI helpers, failing on broken local includes."""
    with tempfile.TemporaryDirectory() as directory:
        staging = Path(directory)
        upstream = staging / "upstream"
        for name in (
            "dt-bindings/zmk/mouse.h",
            "dt-bindings/zmk/keys.h",
            "dt-bindings/zmk/pointing.h",
            "dt-bindings/zmk/bt.h",
            "dt-bindings/zmk/outputs.h",
            "behaviors/mouse_keys.dtsi",
            "behaviors.dtsi",
        ):
            header = upstream / name
            header.parent.mkdir(parents=True, exist_ok=True)
            header.touch()
        # Match build.yml: root helpers first, then keymap helpers, then one
        # entrypoint. Other .keymap files are deliberately absent from staging.
        for source in (ROOT / "config", ROOT / "config/keymap"):
            for helper in source.glob("*.dtsi"):
                shutil.copy2(helper, staging / helper.name)
        shutil.copy2(ROOT / "config/keymap" / keymap, staging / "charybdis.keymap")
        return subprocess.run(
            [
                "cpp", "-P", "-x", "assembler-with-cpp", "-nostdinc", "-undef",
                "-I", str(upstream), "-I", str(staging),
                str(staging / "charybdis.keymap"),
            ],
            check=True, capture_output=True, text=True,
        ).stdout


def layer_bindings(source, layer):
    """Return ordered bindings, rejecting missing layers rather than guessing."""
    match = re.search(r"\b" + re.escape(layer) + r"\s*\{\s*bindings\s*=\s*<(.*?)>;", source, re.S)
    if match is None:
        raise AssertionError(f"Missing layer: {layer}")
    return [" ".join(binding.split()) for binding in re.findall(r"&[^&]+", match[1])]


class KeymapTests(unittest.TestCase):
    """Protect OS-specific shortcuts, fixed key positions, and legacy behavior."""

    def test_linux_gui_shortcuts_preserve_letter_taps(self):
        """Hold shortcuts use Control, but ordinary typing remains unchanged."""
        base = layer_bindings(preprocess("qwerty-linux.keymap"), "BASE")
        for position, letter in ((2, "W"), (5, "T"), (21, "L"), (27, "C"), (28, "V")):
            with self.subTest(position=position):
                self.assertEqual(base[position], f"&cmd_plus LC({letter}) {letter}")

    def test_b_is_plain_b_not_the_old_save_macro(self):
        """Protect quick taps and holds from the historical B-to-:w behavior."""
        for keymap in ("qwerty.keymap", "qwerty-linux.keymap"):
            with self.subTest(keymap=keymap):
                source = preprocess(keymap)
                self.assertEqual(layer_bindings(source, "BASE")[29], "&kp B")
                for layer in ("special_chars", "numbers", "vim_motions", "nvim", "scrolling"):
                    self.assertIn(layer_bindings(source, layer)[29], ("&trans", "&kp B"))

    def test_terminal_clipboard_is_explicit(self):
        """The semicolon-held layer has Ctrl+Shift+C/V, not shell Ctrl+C/V."""
        nav = layer_bindings(preprocess("qwerty-linux.keymap"), "vim_motions")
        self.assertEqual(nav[27], "&kp LC(LS(C))")
        self.assertEqual(nav[28], "&kp LC(LS(V))")

    def test_super_is_not_globally_remapped(self):
        """Keep launcher, workspace shortcuts, and a held Super key available."""
        linux = preprocess("qwerty-linux.keymap")
        base = layer_bindings(linux, "BASE")
        nav = layer_bindings(linux, "vim_motions")
        self.assertEqual(base[35], "&mt RIGHT_GUI SLASH")
        self.assertEqual(base[22], "&lt 3 SEMICOLON")
        self.assertRegex(linux, r"spotlight\s*\{\s*bindings\s*=\s*<&kp RG\(SPACE\)>")
        self.assertEqual(nav[13:18], [f"&kp RG({key})" for key in (
            "NUMBER_1", "NUMBER_2", "NUMBER_3", "NUMBER_4", "NUMBER_5",
        )])

    def test_documented_bootloader_chords_match_both_keymaps(self):
        """The helper's A+Esc and semicolon+backslash guide must match real layers."""
        for keymap in ("qwerty.keymap", "qwerty-linux.keymap"):
            with self.subTest(keymap=keymap):
                source = preprocess(keymap)
                base = layer_bindings(source, "BASE")
                self.assertEqual(base[13], "&lt 1 A")
                self.assertEqual(base[22], "&lt 3 SEMICOLON")
                self.assertEqual(layer_bindings(source, "special_chars")[0], "&bootloader")
                self.assertEqual(layer_bindings(source, "vim_motions")[11], "&bootloader")

    def test_only_intended_linux_bindings_differ(self):
        """Require all six layers to retain their 41-key matrix and other bindings."""
        mac = preprocess("qwerty.keymap")
        linux = preprocess("qwerty-linux.keymap")
        expected_changes = {"BASE": {2, 5, 21, 27, 28}, "vim_motions": {27, 28}}
        for layer in ("BASE", "special_chars", "numbers", "vim_motions", "nvim", "scrolling"):
            with self.subTest(layer=layer):
                before = layer_bindings(mac, layer)
                after = layer_bindings(linux, layer)
                self.assertEqual(len(before), 41)
                self.assertEqual(len(after), 41)
                changed = {i for i, pair in enumerate(zip(before, after)) if pair[0] != pair[1]}
                self.assertEqual(changed, expected_changes.get(layer, set()))

    def test_connection_controls_exist_only_on_held_numbers_layer(self):
        """Both OS maps must be able to clear a stale bond from the keyboard.

        Without &bt bindings a host-side unpair leaves the keyboard holding an
        unusable bond with no on-device recovery. BT_CLR must never be on a
        layer reachable without holding Tab, so it cannot be hit while typing.
        """
        expected = ["&bt BT_SEL 0", "&bt BT_SEL 1", "&bt BT_SEL 2", "&out OUT_TOG", "&bt BT_CLR"]
        for keymap in ("qwerty.keymap", "qwerty-linux.keymap"):
            source = preprocess(keymap)
            with self.subTest(keymap=keymap):
                numbers = layer_bindings(source, "numbers")
                self.assertEqual(numbers[30:35], expected)
                self.assertEqual(numbers[35], "&trans")
                for layer in ("BASE", "special_chars", "vim_motions", "nvim", "scrolling"):
                    joined = " ".join(layer_bindings(source, layer))
                    self.assertNotIn("&bt", joined, layer)
                    self.assertNotIn("&out", joined, layer)

    def test_macos_output_is_unchanged(self):
        """Compare all preprocessed source tokens with the pinned macOS map.

        Updated deliberately when Tab-layer BT/output controls were added.
        """
        normalized = "".join(preprocess("qwerty.keymap").split())
        self.assertEqual(hashlib.sha256(normalized.encode()).hexdigest(), "948c1f7f895593b778dc843748b5331b539fa467ee7eb22e5c14317e1d18a224")

    def test_build_matrix_discovers_linux_bluetooth_and_preserves_macos(self):
        """Existing CI must discover both OS variants without treating DTSI as a map."""
        result = subprocess.run(
            ["python3", "-I", str(ROOT / "scripts/generate_matrix.py")],
            check=True, capture_output=True, text=True,
        )
        matrix = json.loads(result.stdout)
        for keymap in ("qwerty", "qwerty-linux"):
            for transport in ("bt", "dongle"):
                with self.subTest(keymap=keymap, transport=transport):
                    self.assertEqual(sum(row["name"] == f"{keymap}-{transport}" for row in matrix), 1)
        self.assertEqual(sum(row["format"] == "reset" for row in matrix), 1)
        self.assertTrue(all(row["keymap"] != "qwerty.dtsi" for row in matrix))


if __name__ == "__main__":
    unittest.main()
