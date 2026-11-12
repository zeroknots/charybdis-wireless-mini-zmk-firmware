#!/usr/bin/env python3
"""Build the Linux/B-fixed Bluetooth/USB firmware locally inside `nix develop`.

Use West's normal workspace and incremental build directories under .build only.
Never install packages, export CMake packages to HOME, flash hardware, or reset
settings. Existing config/west.yml remains the source manifest used by CI too.
"""

import argparse
import fcntl
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class BuildError(Exception):
    """A failed prerequisite or unsafe build location. No fallback is attempted."""


def command(args, cwd, env):
    """Run West with this shell's Python, preserving output and failure status.

    Nix's standalone West wrapper prepends bare Python to PATH. That makes
    nanopb's env-python shebang lose this shell's protobuf/setuptools modules.
    Invoke the module directly so nested generators retain the complete shell.
    """
    if args[0] != "west":
        raise BuildError("Expected a West build step.")
    argv = [sys.executable, "-I", "-m", "west", *map(str, args[1:])]
    print("+", " ".join(argv), flush=True)
    subprocess.run(argv, cwd=cwd, env=env, check=True)


def stage(root, workspace):
    """Refresh generated config and CI-equivalent overlays, not the user's sources."""
    config = workspace / "config"
    if config.is_symlink():
        raise BuildError(f"Refusing generated config symlink: {config}")
    if config.exists():
        shutil.rmtree(config)
    shutil.copytree(root / "config", config)
    return config


def stage_shields(root, workspace):
    """Stage the bt shields and the Linux entrypoint exactly as the CI build does."""
    app = workspace / "zmk/app"
    shields = app / "boards/shields/charybdis_bt"
    shutil.copytree(root / "boards/shields/charybdis_bt", shields, dirs_exist_ok=True)
    for helper in ("charybdis-layouts.dtsi", "charybdis_pmw3610.dtsi", "charybdis_pointer.dtsi"):
        shutil.copy2(root / "config" / helper, shields / helper)
    overlays = app / "overlays"
    overlays.mkdir(exist_ok=True)
    for source in (root / "config", root / "config/keymap"):
        for helper in source.glob("*.dtsi"):
            shutil.copy2(helper, overlays / helper.name)
    shutil.copy2(root / "config/keymap/qwerty-linux.keymap", overlays / "charybdis.keymap")


def build(root, half, jobs, pristine):
    """Build selected halves sequentially and publish an isolated artifact directory.

    A nonblocking lock prevents concurrent commands from altering the same West
    workspace. Each invocation gets a fresh output directory, so old or partial
    images cannot silently form a mixed bundle. Cached compilation stays reusable.
    """
    root = root.resolve()
    required = (
        "config/west.yml", "config/keymap/qwerty-linux.keymap",
        "config/keymap/qwerty.dtsi", "boards/shields/charybdis_bt/charybdis_right.conf",
    )
    if not all((root / name).is_file() for name in required):
        raise BuildError("Run zmk-build from the keyboard repository root.")
    if not 1 <= jobs <= 4:
        raise BuildError("--jobs must be between 1 and 4 (default 2).")
    for executable in ("west", "cmake", "ninja", "dtc", "git", "protoc"):
        if shutil.which(executable) is None:
            raise BuildError(f"Missing {executable}. Enter the pinned environment with nix develop.")
    if not os.environ.get("ZEPHYR_SDK_INSTALL_DIR"):
        raise BuildError("Missing Zephyr SDK environment. Run inside nix develop.")
    generated = root / ".build"
    workspace = generated / "workspace"
    if generated.is_symlink() or workspace.is_symlink():
        raise BuildError("Refusing a symlinked .build directory or West workspace.")
    workspace.mkdir(parents=True, exist_ok=True)
    with (generated / "build.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BuildError("Another local build owns this workspace. Wait for it; do not stop it.") from error
        config = stage(root, workspace)
        env = dict(os.environ, ZEPHYR_BASE=str(workspace / "zephyr"))
        if not (workspace / ".west").exists():
            command(["west", "init", "-l", config], workspace, env)
        command(["west", "update", "--narrow"], workspace, env)
        stage_shields(root, workspace)
        output_root = generated / "firmware"
        output_root.mkdir(exist_ok=True)
        output = Path(tempfile.mkdtemp(prefix="qwerty-linux-bt-", dir=output_root))
        halves = ("left", "right") if half == "both" else (half,)
        for part in halves:
            build_dir = generated / f"qwerty-linux-{part}"
            flags = [
                "west", "build", "-s", workspace / "zmk/app", "-d", build_dir,
                "-b", "nice_nano_v2", "-p", "always" if pristine else "auto",
                f"--build-opt=-j{jobs}", "--",
                f"-DZMK_CONFIG={config}", f"-DSHIELD=charybdis_{part}",
                "-DKEYMAP_FILE=overlays/charybdis.keymap",
                f"-DZephyr_DIR={workspace / 'zephyr/share/zephyr-package/cmake'}",
                # Refresh cached interpreter selection when the Nix shell changes,
                # and keep Zephyr's compiler-probe cache inside this project.
                f"-DPython3_EXECUTABLE={sys.executable}",
                f"-DUSER_CACHE_DIR={generated / 'cache'}",
                # Old Zephyr/nanopb projects declare CMake policies older than
                # CMake 4 accepts by default. Keep sources unchanged like CI.
                "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
            ]
            if part == "right":
                flags.append("-DSNIPPET=studio-rpc-usb-uart")
            command(flags, workspace, env)
            image = build_dir / "zephyr/zmk.uf2"
            if not image.is_file():
                raise BuildError(f"Build returned without its expected UF2: {image}")
            shutil.copy2(image, output / f"charybdis_{part}.uf2")
        # West update excludes inactive groups. Freeze the same active set;
        # inactive projects may intentionally be absent from the workspace.
        frozen = subprocess.run(
            [sys.executable, "-I", "-m", "west", "manifest", "--freeze", "--active-only"], cwd=workspace, env=env,
            check=True, capture_output=True, text=True,
        ).stdout
        (output / "west-manifest.yml").write_text(frozen)
        print(f"\nFirmware: {output}")
        print(f"Validate without flashing: zmk-flash '{output}' --half {half} --dry-run")
        print("No hardware was flashed. Save a known-good bundle before flashing.")
        return output


def main():
    """Parse bounded build options and return nonzero without retrying failed steps."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--half", choices=("right", "left", "both"), default="right")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--pristine", action="store_true", help="ask West to rebuild the selected cached build directories")
    args = parser.parse_args()
    try:
        build(args.repo, args.half, args.jobs, args.pristine)
    except (BuildError, OSError, subprocess.CalledProcessError) as error:
        print(f"Build stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
