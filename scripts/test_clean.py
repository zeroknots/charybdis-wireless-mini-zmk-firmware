#!/usr/bin/env python3
"""Test cleanup containment and preservation on disposable files, not real clones."""
import contextlib
import fcntl
import importlib.util
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(os.environ.get("CHARYBDIS_TEST_ROOT", Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location("charybdis_clean", ROOT / "scripts/clean.py")
CLEAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLEAN)


class CleanupTests(unittest.TestCase):
    """A cleanup request must never become a source, artifact or dirty-work deletion."""
    def setUp(self):
        """Create downloaded-clone and artifact stand-ins with no global side effects."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / ".build/workspace"
        (self.workspace / ".west").mkdir(parents=True)
        self.project = SimpleNamespace(name="unused", path="modules/unused")
        self.clone = self.workspace / self.project.path
        (self.clone / ".git").mkdir(parents=True)
        (self.clone / "downloaded.c").write_text("downloaded")
        self.artifact = self.root / ".build/firmware/known-good.uf2"
        self.artifact.parent.mkdir()
        self.artifact.write_bytes(b"preserve firmware")
        self.git_results = {
            "rev-parse --show-toplevel": (0, str(self.clone) + "\n"),
            "rev-parse HEAD": (0, "abc\n"),
            "rev-parse refs/heads/manifest-rev": (0, "abc\n"),
            "status --porcelain --untracked-files=all --ignored=matching": (0, ""),
            "for-each-ref --format=%(refname)": (0, "refs/heads/manifest-rev\n"),
            "symbolic-ref -q HEAD": (1, ""),
            "rev-parse --verify --quiet refs/stash": (1, ""),
            "worktree list --porcelain": (0, f"worktree {self.clone}\nHEAD abc\ndetached\n"),
            "reflog --all --format=%H": (0, "abc\n"),
            "merge-base --is-ancestor abc abc": (0, ""),
            "merge-base --is-ancestor user abc": (1, ""),
        }

    def git(self, args, **kwargs):
        """Supply Git's external state independently of the cleanup implementation."""
        del kwargs
        code, output = self.git_results[" ".join(args[3:])]
        return SimpleNamespace(returncode=code, stdout=output)

    def invoke(self, apply):
        """Keep graph discovery separate while checking real lock and deletion behavior."""
        with mock.patch.object(CLEAN, "projects", return_value=[self.project]), \
                mock.patch.object(CLEAN.subprocess, "run", side_effect=self.git), \
                contextlib.redirect_stdout(io.StringIO()):
            return CLEAN.clean(self.root, apply)

    def test_preview_does_not_delete_and_apply_preserves_artifacts(self):
        """Only an applied, verified unused clone is deleted; saved firmware remains."""
        self.assertEqual(self.invoke(False), 1)
        self.assertTrue(self.clone.exists())
        self.assertEqual(self.invoke(True), 1)
        self.assertFalse(self.clone.exists())
        self.assertEqual(self.artifact.read_bytes(), b"preserve firmware")

    def test_dirty_local_branches_or_wrong_revision_are_kept(self):
        """Protect plausible local changes even inside a generated download directory."""
        cases = (
            ("status --porcelain --untracked-files=all --ignored=matching", (0, " M downloaded.c\n")),
            ("status --porcelain --untracked-files=all --ignored=matching", (0, "?? notes.txt\n")),
            ("status --porcelain --untracked-files=all --ignored=matching", (0, "!! ignored-notes.txt\n")),
            ("rev-parse HEAD", (0, "user-commit\n")),
            ("for-each-ref --format=%(refname)", (0, "refs/heads/manifest-rev\nrefs/heads/my-work\n")),
            ("symbolic-ref -q HEAD", (0, "refs/heads/manifest-rev\n")),
            ("rev-parse HEAD", (128, "")),
            ("rev-parse --verify --quiet refs/stash", (0, "saved-work\n")),
            ("worktree list --porcelain", (0, "worktree one\n\nworktree two\n")),
            ("reflog --all --format=%H", (0, "user\n")),
            ("for-each-ref --format=%(refname)", (0, "refs/heads/manifest-rev\nrefs/tags/my-work\n")),
        )
        for command, result in cases:
            with self.subTest(command=command, result=result), mock.patch.dict(self.git_results, {command: result}):
                self.assertEqual(self.invoke(True), 0)
                self.assertTrue((self.clone / "downloaded.c").is_file())

    def test_paths_outside_modules_and_symlinks_are_never_removed(self):
        """Do not trust absolute paths, parent traversals, worktrees or symlinked parents."""
        for path in ("../escape", "/tmp/elsewhere", "config", "modules/../../firmware"):
            with self.subTest(path=path):
                self.assertIsNone(CLEAN.safe_clone(self.workspace, SimpleNamespace(path=path)))
        alias = self.workspace / "modules/alias"
        alias.symlink_to(self.clone, target_is_directory=True)
        self.assertIsNone(CLEAN.safe_clone(self.workspace, SimpleNamespace(path="modules/alias")))

    def test_active_build_prevents_deletion(self):
        """An active normal build lock is a stop condition, not a cancellation request."""
        with (self.root / ".build/build.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(CLEAN.CleanError):
                self.invoke(True)
        self.assertTrue(self.clone.exists())

    def test_changed_git_state_before_removal_is_refused(self):
        """A clone becoming dirty between preview and removal must remain intact."""
        with mock.patch.object(CLEAN, "projects", return_value=[self.project]), \
                mock.patch.object(CLEAN, "safe_clone", side_effect=[self.clone, None]), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(CLEAN.CleanError):
                CLEAN.clean(self.root, True)
        self.assertTrue(self.clone.exists())


if __name__ == "__main__":
    unittest.main()
