from contextlib import ExitStack, redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dotfiles_restore", ROOT / "scripts/restore.py")
restore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(restore)
link_spec = importlib.util.spec_from_file_location("restore_links", ROOT / "scripts/links.py")
links = importlib.util.module_from_spec(link_spec)
link_spec.loader.exec_module(links)


class RestoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="restore-test-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / "home"
        (self.home / "Main").mkdir(parents=True)
        (self.home / "Main/existing.txt").write_text("keep existing data")
        self.existing_config = self.home / ".config/rclone/rclone.conf"
        self.existing_config.parent.mkdir(parents=True)
        self.existing_config.write_text("keep existing account config")
        self.profile = ROOT / "restore.json"
        self.phrase = "fixture phrase only"
        self.configs = []
        self.commands = []
        self.failed_attempts = 0
        self.fail_restore = False
        self.records = [{"id": "a" * 64, "time": "2026-10-30T10:00:00Z", "hostname": "fixture", "paths": ["/fixture/Main"], "tags": ["main-only"]}]
        self.output = io.StringIO()

    def configure(self, command, env, cwd):
        self.assertEqual(command[0:2], ["rclone", "--config"])
        self.assertEqual(command[-1], "config")
        config = Path(command[2])
        self.assertNotEqual(config, self.existing_config)
        config.write_text("[gdrive]\ntype=drive\n")
        self.configs.append(config)
        self.assertNotIn("RCLONE_CONFIG_GDRIVE_TOKEN", env)
        self.assertNotIn("RESTIC_PASSWORD", env)
        return SimpleNamespace(returncode=0)

    def command(self, command, env, work, operation):
        self.commands.append((command, dict(env)))
        self.assertNotIn(self.phrase, command)
        if command[0] == "rclone":
            return b"gdrive:\n"
        self.assertIn("--no-lock", command)
        if "snapshots" in command:
            if self.failed_attempts:
                self.failed_attempts -= 1
                raise restore.CommandError(operation, 12)
            return json.dumps(self.records).encode()
        self.assertIn("restore", command)
        self.assertIn("--verify", command)
        self.assertEqual(command[command.index("--overwrite") + 1], "never")
        self.assertIn("a" * 64 + ":/Main", command)
        target = Path(command[command.index("--target") + 1])
        target.mkdir()
        (target / "restored.txt").write_text("restored fixture")
        if self.fail_restore:
            raise restore.CommandError(operation, 1)
        return b""

    def execute(self, answers=None, phrases=None):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"HOME": str(self.home), "RESTIC_PASSWORD": "ignored caller value", "RCLONE_CONFIG": str(self.existing_config), "RCLONE_CONFIG_GDRIVE_TOKEN": "ignored caller token"}))
            stack.enter_context(patch("builtins.input", side_effect=answers or [""]))
            stack.enter_context(patch.object(restore.getpass, "getpass", side_effect=phrases or [self.phrase]))
            stack.enter_context(patch.object(restore.subprocess, "run", side_effect=self.configure))
            stack.enter_context(patch.object(restore, "run_private", side_effect=self.command))
            stack.enter_context(redirect_stdout(self.output))
            stack.enter_context(redirect_stderr(self.output))
            return restore.restore_files(self.profile)

    def assert_private_cleanup(self):
        self.assertTrue(self.configs)
        self.assertTrue(all(not config.parent.exists() for config in self.configs))
        self.assertEqual(self.existing_config.read_text(), "keep existing account config")
        self.assertEqual((self.home / "Main/existing.txt").read_text(), "keep existing data")
        self.assertNotIn(self.phrase, self.output.getvalue())

    def test_success_isolated_from_existing_files_and_credentials(self):
        target = self.execute()
        self.assertEqual((target / "restored.txt").read_text(), "restored fixture")
        self.assertTrue((target.parent / ".RESTORE_COMPLETE").is_file())
        self.assertFalse((target.parent / ".RESTORE_INCOMPLETE").exists())
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assert_private_cleanup()

    def test_restore_failure_keeps_partial_data_and_cleans_access(self):
        self.fail_restore = True
        with self.assertRaises(restore.CommandError):
            self.execute()
        partial = list(self.home.glob("Restored-Main-*"))
        self.assertEqual(len(partial), 1)
        self.assertTrue((partial[0] / ".RESTORE_INCOMPLETE").is_file())
        self.assertFalse((partial[0] / ".RESTORE_COMPLETE").exists())
        self.assertTrue((partial[0] / "Main/restored.txt").exists())
        self.assert_private_cleanup()

    def test_wrong_password_can_be_retried_without_reauthorizing(self):
        self.failed_attempts = 1
        self.execute(phrases=["wrong fixture", self.phrase])
        self.assertEqual(len(self.configs), 1)
        self.assertEqual(sum("snapshots" in command for command, _ in self.commands), 2)
        self.assert_private_cleanup()

    def test_three_wrong_attempts_stop_without_creating_destination(self):
        self.failed_attempts = 3
        with self.assertRaises(restore.RestoreError):
            self.execute(phrases=[self.phrase] * 3)
        self.assertEqual(list(self.home.glob("Restored-Main-*")), [])
        self.assert_private_cleanup()

    def test_other_tags_or_sources_are_never_restored(self):
        self.records[0]["tags"] = ["different"]
        with self.assertRaises(restore.RestoreError):
            self.execute()
        self.assertFalse(any("restore" in command for command, _ in self.commands))
        self.assertEqual(list(self.home.glob("Restored-Main-*")), [])
        self.assert_private_cleanup()

    def test_ambiguous_snapshot_prefix_is_rejected(self):
        self.records.append({**self.records[0], "id": "a" * 8 + "b" * 56})
        with self.assertRaises(restore.RestoreError):
            self.execute(answers=["a" * 8])
        self.assertEqual(list(self.home.glob("Restored-Main-*")), [])
        self.assert_private_cleanup()

    def test_cancelled_snapshot_selection_cleans_credentials(self):
        with self.assertRaises(KeyboardInterrupt):
            self.execute(answers=[KeyboardInterrupt()])
        self.assert_private_cleanup()

    def test_profile_rejects_urls_and_parent_paths(self):
        profile = json.loads(self.profile.read_text())
        path = self.base / "invalid.json"
        for value in ["../backup", "/backup", "https://example.invalid/backup"]:
            profile["repository_path"] = value
            path.write_text(json.dumps(profile))
            with self.assertRaises(restore.RestoreError):
                restore.load_profile(path)

    def test_child_output_does_not_expose_input_on_error(self):
        with tempfile.TemporaryDirectory(dir=self.base) as td:
            work = Path(td)
            env = {**os.environ, "HOME": str(self.home), "RESTIC_PASSWORD": self.phrase}
            code = "import os,sys; print(os.environ['RESTIC_PASSWORD']); print(os.environ['RESTIC_PASSWORD'], file=sys.stderr); sys.exit(7)"
            with redirect_stdout(self.output), redirect_stderr(self.output):
                with self.assertRaises(restore.CommandError) as raised:
                    restore.run_private([sys.executable, "-c", code], env, work, "fixture")
            self.assertNotIn(self.phrase, str(raised.exception) + self.output.getvalue())
            self.assertEqual(list(work.iterdir()), [])


@unittest.skipUnless(shutil.which("restic") and shutil.which("rclone"), "native Restic/rclone are optional for the local integration test")
class NativeRestoreTests(unittest.TestCase):
    def test_native_restic_through_local_rclone_restores_and_verifies_main(self):
        with tempfile.TemporaryDirectory(prefix="native-restore-") as td:
            base = Path(td)
            source = base / "source"
            (source / "Main/project/node_modules").mkdir(parents=True)
            (source / "Main/project/node_modules/ignored.txt").write_text("excluded")
            (source / "Main/data.bin").write_bytes(bytes(range(256)))
            (source / "Main/notes.txt").write_text("native local fixture\n")
            for relative in links.CONFIGS:
                config = source / "Main" / links.CONFIG_DIRECTORY / links.CONFIG_FILES[relative]
                config.parent.mkdir(parents=True, exist_ok=True)
                config.write_text("# restored config fixture\n")
            storage = base / "storage"
            repository = storage / "backups/main-restic"
            repository.mkdir(parents=True)
            home = base / "home"
            (home / "Main").mkdir(parents=True)
            (home / "Main/existing.txt").write_text("do not replace")
            phrase = "native fixture phrase"
            env = {key: value for key, value in os.environ.items() if not key.startswith(("RESTIC_", "RCLONE_"))}
            env.update(RESTIC_PASSWORD=phrase, HOME=str(home))
            prefix = [shutil.which("restic"), "--repo", str(repository), "--cache-dir", str(base / "cache")]
            subprocess.run(prefix + ["init"], env=env, capture_output=True, check=True, timeout=30)
            subprocess.run(prefix + ["backup", "--tag", "main-only", "--exclude", "Main/**/node_modules", "--", "Main"], env=env, cwd=source, capture_output=True, check=True, timeout=30)
            def contents():
                return {p.relative_to(repository).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in repository.rglob("*") if p.is_file()}
            before = contents()
            configs = []
            def configure(command, env, cwd):
                config = Path(command[2])
                config.write_text("[gdrive]\ntype=alias\nremote=" + str(storage) + "\n")
                configs.append(config)
                return SimpleNamespace(returncode=0)
            output = io.StringIO()
            with patch.dict(os.environ, {"HOME": str(home)}), patch.object(restore.subprocess, "run", side_effect=configure), patch.object(restore.getpass, "getpass", return_value=phrase), patch("builtins.input", return_value=""), redirect_stdout(output):
                target = restore.restore_files(ROOT / "restore.json")
            self.assertEqual((target / "data.bin").read_bytes(), bytes(range(256)))
            self.assertEqual((target / "notes.txt").read_text(), "native local fixture\n")
            self.assertFalse((target / "project/node_modules").exists())
            self.assertEqual((home / "Main/existing.txt").read_text(), "do not replace")
            self.assertEqual(contents(), before)
            self.assertTrue((target.parent / ".RESTORE_COMPLETE").is_file())
            self.assertTrue(all(not config.parent.exists() for config in configs))
            self.assertNotIn(phrase, output.getvalue())
            with self.assertRaises(links.LinkError):
                links.adopt_main(target, home)
            os.rename(home / "Main", home / "Main-existing-fixture")
            current_env = {key: value for key, value in os.environ.items() if key not in {"XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "ZDOTDIR", "STARSHIP_CONFIG"}}
            current_env["HOME"] = str(home)
            with patch.dict(os.environ, current_env, clear=True), redirect_stdout(output):
                links.adopt_main(target, home)
                links.apply(home)
            for source_config, config_link in links.plan(home):
                self.assertTrue(links.correct_link(source_config, config_link))
            self.assertEqual((home / "Main-existing-fixture/existing.txt").read_text(), "do not replace")


if __name__ == "__main__":
    unittest.main()
