#!/usr/bin/env python3
"""Preview or remove unused downloaded West projects, never source or firmware.

Use --apply to remove only clean, detached clones at their recorded manifest
revision under .build/workspace/modules. Preserve dirty repositories, local
branches, symlinks, all firmware bundles, build caches, and the global Nix store.
"""

import argparse
import fcntl
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


class CleanError(Exception):
    """An unsafe or active workspace prevents cleanup rather than broadening it."""


def projects(root, workspace):
    """Compare the filtered manifest with the original upstream import graph offline."""
    import yaml
    from west.manifest import Manifest

    data = yaml.safe_load((root / "config/west.yml").read_text())
    # West's data-only parser cannot resolve Zephyr's nested self-imports. Use
    # ordinary temporary workspace metadata and symlink existing clones into it.
    # No real manifest/config is changed, no project is fetched, and removing
    # the temporary directory does not follow its symlinks into the cache.
    with tempfile.TemporaryDirectory(prefix="manifest-preview-", dir=root / ".build") as directory:
        view = Path(directory)
        (view / ".west").mkdir()
        (view / ".west/config").write_text("[manifest]\npath = config\nfile = west.yml\n")
        (view / "config").mkdir()
        for path in workspace.iterdir():
            if path.name not in ("config", ".west") and path.is_dir():
                (view / path.name).symlink_to(path, target_is_directory=True)
        source = view / "config/west.yml"
        source.write_text(yaml.safe_dump(data))
        filtered = Manifest(topdir=str(view))
        keep = {project.name for project in filtered.projects}
        for project in data["manifest"]["projects"]:
            if project["name"] == "zmk":
                project["import"] = "app/west.yml"
        source.write_text(yaml.safe_dump(data))
        original = Manifest(topdir=str(view))
        return [project for project in original.projects if project.name not in keep]


def safe_clone(workspace, project):
    """Return a removable clone path, refusing altered Git state or path escapes."""
    relative = Path(project.path)
    if relative.is_absolute() or ".." in relative.parts or relative.parts[:1] != ("modules",):
        return None
    path = workspace / relative
    if not path.exists():
        return None
    current = path
    while current != workspace:
        if current.is_symlink():
            return None
        current = current.parent
    if not (path / ".git").is_dir() or (path / ".git").is_symlink():
        return None
    def git(*args):
        """Read only this clone's Git metadata; any error makes it non-removable."""
        return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    top = git("rev-parse", "--show-toplevel")
    head = git("rev-parse", "HEAD")
    manifest = git("rev-parse", "refs/heads/manifest-rev")
    # Ignored files may also contain local work. Prefer retaining an otherwise
    # disposable clone to deleting data that Git's normal status would hide.
    status = git("status", "--porcelain", "--untracked-files=all", "--ignored=matching")
    branches = git("for-each-ref", "--format=%(refname)")
    symbolic = git("symbolic-ref", "-q", "HEAD")
    stash = git("rev-parse", "--verify", "--quiet", "refs/stash")
    worktrees = git("worktree", "list", "--porcelain")
    reflog = git("reflog", "--all", "--format=%H")
    if any(result.returncode for result in (top, head, manifest, status, branches, worktrees, reflog)):
        return None
    if stash.returncode != 1 or sum(line.startswith("worktree ") for line in worktrees.stdout.splitlines()) != 1:
        return None
    if Path(top.stdout.strip()).resolve() != path.resolve() or head.stdout != manifest.stdout:
        return None
    if status.stdout or symbolic.returncode != 1:
        return None
    if set(branches.stdout.splitlines()) != {"refs/heads/manifest-rev"}:
        return None
    # Preserve detached user commits still recoverable through a reflog, even
    # after the working tree was reset to manifest-rev and appears clean.
    for revision in set(reflog.stdout.splitlines()):
        if git("merge-base", "--is-ancestor", revision, manifest.stdout.strip()).returncode != 0:
            return None
    return path


def clean(root, apply=False):
    """Hold the normal build lock while pruning only individually verified clones."""
    root = root.resolve()
    generated = root / ".build"
    workspace = generated / "workspace"
    if generated.is_symlink() or workspace.is_symlink() or not (workspace / ".west").is_dir():
        raise CleanError("No ordinary initialized build workspace. Nothing removed.")
    removed = 0
    with (generated / "build.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CleanError("A build is active. Wait for it; do not stop or relocate it.") from error
        for project in projects(root, workspace):
            path = safe_clone(workspace, project)
            if path is None:
                if (workspace / project.path).exists():
                    print(f"Kept {project.name}: not a verified clean, detached downloaded clone.")
                continue
            print(f"{'Removing' if apply else 'Would remove'} {path.relative_to(workspace)}")
            if apply:
                # Recheck immediately before removal while holding our build lock.
                if safe_clone(workspace, project) != path:
                    raise CleanError(f"Git state changed before removal: {project.name}")
                shutil.rmtree(path)
            removed += 1
    print(f"{'Removed' if apply else 'Eligible'}: {removed} unused downloaded projects.")
    print("Source, firmware bundles, compiler caches and the Nix store were preserved.")
    return removed


def main():
    """Default to a preview; only an explicit --apply deletes downloaded clones."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        clean(args.repo, args.apply)
    except (CleanError, OSError, ValueError) as error:
        print(f"Cleanup stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
