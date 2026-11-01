from contextlib import redirect_stdout
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("config_links", ROOT / "scripts/links.py")
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)


class LinkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="main-links-")
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / "home"
        self.home.mkdir()
        self.sources = self.home / "Main" / links.CONFIG_DIRECTORY
        for relative in links.CONFIGS:
            source = self.sources / links.CONFIG_FILES[relative]
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# fixture config\n")
        env = {key: value for key, value in os.environ.items() if key not in {"XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "ZDOTDIR", "STARSHIP_CONFIG"}}
        env["HOME"] = str(self.home)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, env, clear=True).start()

    def apply(self):
        with redirect_stdout(io.StringIO()):
            return links.apply(self.home)

    def test_nine_links_point_into_main_and_writes_update_main(self):
        self.apply()
        for source, target in links.plan(self.home):
            self.assertTrue(links.correct_link(source, target))
        target = self.home / ".config/starship.toml"
        target.write_text("# changed by application\n")
        self.assertEqual((self.sources / links.CONFIG_FILES[".config/starship.toml"]).read_text(), "# changed by application\n")
        self.assertIsNone(self.apply())

    def test_replaced_regular_file_is_backed_up_with_mode_and_time(self):
        target = self.home / ".zshrc"
        target.write_text("old user config")
        target.chmod(0o600)
        os.utime(target, (1600000000, 1600000000))
        backup = self.apply()
        saved = backup / ".zshrc"
        self.assertEqual(saved.read_text(), "old user config")
        self.assertEqual(saved.stat().st_mode & 0o777, 0o600)
        self.assertEqual(int(saved.stat().st_mtime), 1600000000)
        self.assertEqual(backup.stat().st_mode & 0o777, 0o700)

    def test_existing_other_symlink_is_backed_up_without_changing_its_target(self):
        outside = self.home.parent / "outside"
        outside.write_text("keep outside")
        (self.home / ".zshrc").symlink_to(outside)
        backup = self.apply()
        self.assertTrue((backup / ".zshrc").is_symlink())
        self.assertEqual(os.readlink(backup / ".zshrc"), str(outside))
        self.assertEqual(outside.read_text(), "keep outside")

    def test_broken_old_symlink_can_be_replaced_and_preserved(self):
        missing = self.home.parent / "missing"
        (self.home / ".zshrc").symlink_to(missing)
        backup = self.apply()
        self.assertEqual(os.readlink(backup / ".zshrc"), str(missing))
        self.assertTrue((self.home / ".zshrc").is_file())

    def test_missing_source_prevents_every_link_change(self):
        (self.sources / links.CONFIG_FILES[".config/mpv/mpv.conf"]).unlink()
        with self.assertRaises(links.LinkError):
            self.apply()
        self.assertFalse((self.home / ".zshrc").exists())

    def test_source_symlink_is_rejected(self):
        source = self.sources / links.CONFIG_FILES[".zshrc"]
        source.unlink()
        source.symlink_to(self.sources / links.CONFIG_FILES[".config/starship.toml"])
        with self.assertRaises(links.LinkError):
            self.apply()

    def test_directory_target_and_parent_symlink_are_rejected(self):
        (self.home / ".zshrc").mkdir()
        with self.assertRaises(links.LinkError):
            self.apply()
        (self.home / ".zshrc").rmdir()
        outside = self.home.parent / "outside"
        outside.mkdir()
        (self.home / ".config").symlink_to(outside)
        with self.assertRaises(links.LinkError):
            self.apply()
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_replacement_rolls_back_prior_links(self):
        target = self.home / ".zshrc"
        target.write_text("original")
        native = os.replace
        def fail_second(source, destination):
            if Path(destination).name == "starship.toml":
                raise PermissionError("fixture failure")
            return native(source, destination)
        with patch.object(links.os, "replace", side_effect=fail_second), self.assertRaises(PermissionError):
            self.apply()
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), "original")
        self.assertEqual(list(self.home.rglob(".dotfiles-link-*")), [])

    def test_adopt_main_refuses_existing_main(self):
        with self.assertRaises(links.LinkError):
            links.adopt_main(self.home / "staged/Main", self.home)
        self.assertTrue(self.sources.is_dir())

    def test_adopt_restored_main_requires_all_configs_and_preserves_paths(self):
        staged = self.home / "Restored-Main-fixture/Main"
        staged.parent.mkdir()
        os.rename(self.home / "Main", staged)
        (staged.parent / ".RESTORE_COMPLETE").write_text("fixture")
        result = links.adopt_main(staged, self.home)
        self.assertEqual(result, self.home / "Main")
        self.assertTrue(self.sources.is_dir())
        self.assertFalse(staged.parent.exists())
        self.apply()

    def make_legacy_layout(self):
        legacy = self.home / "Main" / links.LEGACY_DIRECTORY
        for relative in links.CONFIGS:
            target = legacy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.sources / links.CONFIG_FILES[relative], target)
        shutil.rmtree(self.home / "Main/System")
        return legacy

    def test_old_restic_layout_works_and_links_can_move_to_new_layout(self):
        legacy = self.make_legacy_layout()
        self.apply()
        self.assertEqual((self.home / ".zshrc").resolve(), legacy / ".zshrc")
        for relative in links.CONFIGS:
            target = self.sources / links.CONFIG_FILES[relative]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy / relative, target)
        backup = self.apply()
        for source, target in links.plan(self.home):
            self.assertTrue(links.correct_link(source, target))
        self.assertEqual((self.home / ".zshrc").resolve(), self.sources / "zsh/zshrc")
        self.assertEqual(os.readlink(backup / ".zshrc"), str(legacy / ".zshrc"))
        self.assertTrue((legacy / ".zshrc").is_file())

    def test_partial_new_layout_never_falls_back_to_legacy(self):
        legacy = self.make_legacy_layout()
        self.apply()
        self.sources.mkdir(parents=True)
        with self.assertRaises(links.LinkError):
            self.apply()
        self.assertEqual((self.home / ".zshrc").resolve(), legacy / ".zshrc")

    @unittest.skipUnless(shutil.which("kwriteconfig6"), "native KDE config writer is optional")
    def test_native_kde_writer_keeps_link_and_updates_main_config(self):
        self.apply()
        target = self.home / ".config/dolphinrc"
        subprocess.run([shutil.which("kwriteconfig6"), "--file", str(target), "--group", "General", "--key", "ShowFullPath", "false"], env=os.environ, capture_output=True, check=True, timeout=15)
        self.assertTrue(target.is_symlink())
        self.assertIn("ShowFullPath=false", (self.sources / links.CONFIG_FILES[".config/dolphinrc"]).read_text())


if __name__ == "__main__":
    unittest.main()
