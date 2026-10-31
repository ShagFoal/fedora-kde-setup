import hashlib
import io
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIGS = [
    ".zshrc", ".config/starship.toml", ".config/konsolerc",
    ".local/share/konsole/Profile 1.profile",
    ".local/share/konsole/Catppuccin-Mocha.colorscheme",
    ".config/fastfetch/config.jsonc",
    ".config/dolphinrc",
    ".local/share/kxmlgui5/dolphin/dolphinui.rc",
    ".config/mpv/mpv.conf",
    ".config/kxkbrc",
]
MOCK = '''#!/usr/bin/python3
import os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(name + '\\n')
marker = pathlib.Path(os.environ['PACKAGE_MARKER'])
if name == 'rpm':
    sys.exit(1 if sys.argv[-1] == 'zsh' and not marker.exists() else 0)
if name == 'sudo':
    assert not os.environ.get('FORBID_SUDO'), 'Unexpected sudo'
    assert sys.argv[1:4] == ['dnf', 'install', '-y']
    assert 'mpv' not in sys.argv[4:], 'MPV must be installed by the user'
    marker.touch()
elif name == 'curl':
    assert not os.environ.get('FORBID_DOWNLOAD'), 'Unexpected network request'
    output = pathlib.Path(sys.argv[sys.argv.index('--output') + 1])
    if os.environ.get('CORRUPT_DOWNLOAD'):
        output.write_bytes(b'corrupted')
    else:
        shutil.copyfile(pathlib.Path(os.environ['FIXTURES']) / sys.argv[-1].split('/')[-1], output)
elif name not in ('fc-cache', 'zsh'):
    raise SystemExit('Unexpected command: ' + name)
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(directory):
    result = {}
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            result[str(path.relative_to(directory))] = (
                path.read_bytes(), path.stat().st_mode & 0o777, path.stat().st_mtime_ns,
            )
        elif path.is_symlink():
            result[str(path.relative_to(directory))] = ("symlink", os.readlink(path))
        elif path.is_dir():
            result[str(path.relative_to(directory))] = ("directory",)
    return result


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dotfiles-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.fixtures = self.base / "fixtures"
        self.fixtures.mkdir()
        self.log = self.base / "calls"
        for name in ["rpm", "sudo", "dnf", "curl", "fc-cache", "zsh"]:
            command = self.bin / name
            command.write_text(MOCK)
            command.chmod(0o755)
        self.env = dict(os.environ)
        for name in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "ZDOTDIR", "STARSHIP_CONFIG", "BASH_ENV", "ENV"]:
            self.env.pop(name, None)
        self.env.update(
            HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin",
            CALL_LOG=str(self.log), PACKAGE_MARKER=str(self.base / "packages-installed"),
            FIXTURES=str(self.fixtures),
        )
        self.rows = []
        for component in ["starship", "zsh-patina"]:
            payload = b"#!/bin/sh\nexit 0\n"
            archive = self.fixtures / f"{component}.tar.gz"
            self.make_archive(archive, {component: payload})
            self.rows.append(["all", f"https://github.com/starship/starship/releases/download/test/{archive.name}", digest(archive.read_bytes()), component, digest(payload), f".local/bin/{component}", "755"])
        font = self.fixtures / "font.tar.gz"
        members = {"Regular.ttf": b"font fixture", "OFL.txt": b"license fixture"}
        self.make_archive(font, members)
        for name, payload in members.items():
            self.rows.append(["all", f"https://github.com/ryanoasis/nerd-fonts/releases/download/test/{font.name}", digest(font.read_bytes()), name, digest(payload), f".local/share/fonts/JetBrainsMonoNerdFont/{name}", "644"])
        for name in ["zsh-autosuggestions.zsh", "LICENSE"]:
            payload = b"# autosuggestions fixture\n"
            (self.fixtures / name).write_bytes(payload)
            self.rows.append(["all", f"https://raw.githubusercontent.com/zsh-users/zsh-autosuggestions/test/{name}", digest(payload), "-", digest(payload), f".zsh/zsh-autosuggestions/{name}", "644"])
        self.update_lock()

    @staticmethod
    def make_archive(path, members):
        with tarfile.open(path, "w:gz") as archive:
            for name, payload in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                archive.addfile(info, io.BytesIO(payload))

    def update_lock(self):
        (self.repo / "dependencies.tsv").write_text("\n".join("\t".join(row) for row in self.rows) + "\n")
        files = sorted(p for p in self.repo.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
        (self.repo / "SHA256SUMS").write_text("".join(f"{digest(p.read_bytes())}  {p.relative_to(self.repo).as_posix()}\n" for p in files))

    def run_installer(self, *args, success=True, **environment):
        result = subprocess.run(
            ["bash", str(self.repo / "install.sh"), *args], cwd=self.base,
            env={**self.env, **environment}, text=True, capture_output=True, timeout=30,
        )
        if success:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_dry_run_has_no_filesystem_network_or_sudo_changes(self):
        before = snapshot(self.home)
        self.run_installer("--dry-run", FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual(snapshot(self.home), before)
        self.assertTrue(all(call == "rpm" for call in self.calls()))

    def test_install_backup_and_offline_idempotence(self):
        original = self.home / ".zshrc"
        original.write_text("original config\n")
        original.chmod(0o600)
        os.utime(original, (1600000000, 1600000000))
        self.run_installer()
        backups = list((self.home / ".local/state/dotfiles/backups").glob("*/.zshrc"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "original config\n")
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(int(backups[0].stat().st_mtime), 1600000000)
        for relative in CONFIGS:
            self.assertEqual((self.home / relative).read_bytes(), (self.repo / "files" / relative).read_bytes())
            self.assertFalse((self.home / relative).is_symlink())
        self.assertTrue(os.access(self.home / ".local/bin/starship", os.X_OK))
        before = snapshot(self.home)
        self.log.write_text("")
        result = self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertIn("Files changed: 0", result.stdout)
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn("fc-cache", self.calls())
        self.run_installer("--check", FORBID_DOWNLOAD="1", FORBID_SUDO="1")

    def test_changed_config_gets_a_new_backup(self):
        self.run_installer()
        target = self.home / ".config/starship.toml"
        for content in ["first edit", "second edit"]:
            target.write_text(content)
            self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        backups = list((self.home / ".local/state/dotfiles/backups").glob("*/.config/starship.toml"))
        self.assertEqual({p.read_text() for p in backups}, {"first edit", "second edit"})

    def test_corrupt_download_does_not_replace_configs(self):
        (self.home / ".zshrc").write_text("keep me")
        result = self.run_installer(success=False, CORRUPT_DOWNLOAD="1")
        self.assertIn("checksum mismatch", result.stderr)
        self.assertEqual((self.home / ".zshrc").read_text(), "keep me")
        self.assertFalse((self.home / ".local/bin/starship").exists())

    def test_symlink_target_is_rejected_before_sudo_or_download(self):
        outside = self.base / "outside"
        outside.write_text("keep outside")
        (self.home / ".zshrc").symlink_to(outside)
        self.run_installer(success=False)
        self.assertEqual(outside.read_text(), "keep outside")
        self.assertNotIn("sudo", self.calls())
        self.assertNotIn("curl", self.calls())

    def test_symlink_parent_is_rejected_before_mutation(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / ".config").symlink_to(outside, target_is_directory=True)
        self.run_installer(success=False)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertNotIn("sudo", self.calls())

    def test_directory_target_is_rejected(self):
        (self.home / ".zshrc").mkdir()
        self.run_installer(success=False)
        self.assertNotIn("sudo", self.calls())

    def test_manifest_tamper_is_rejected_before_mutation(self):
        with (self.repo / "files/.zshrc").open("a") as output:
            output.write("\n# changed\n")
        self.run_installer("--dry-run", success=False)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_check_detects_drift_without_writing(self):
        self.run_installer()
        (self.home / ".zshrc").write_text("local edit")
        before = snapshot(self.home)
        self.run_installer("--check", success=False, FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual(snapshot(self.home), before)

    def test_xdg_and_zdotdir_inside_home(self):
        self.env.update(
            XDG_CONFIG_HOME=str(self.home / "settings"),
            XDG_DATA_HOME=str(self.home / "data"),
            XDG_STATE_HOME=str(self.home / "state"),
            ZDOTDIR=str(self.home / "shell"),
        )
        self.run_installer()
        self.assertTrue((self.home / "shell/.zshrc").is_file())
        self.assertTrue((self.home / "settings/starship.toml").is_file())
        self.assertTrue((self.home / "data/konsole/Profile 1.profile").is_file())
        self.assertFalse((self.home / ".config").exists())
        self.run_installer("--check")

    def test_archive_symlink_is_rejected(self):
        outside = self.base / "outside"
        outside.write_text("keep outside")
        archive_path = self.fixtures / "starship.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            link = tarfile.TarInfo("starship")
            link.type = tarfile.SYMTYPE
            link.linkname = str(outside)
            archive.addfile(link)
        self.rows[0][2] = digest(archive_path.read_bytes())
        self.update_lock()
        result = self.run_installer(success=False)
        self.assertIn("regular archive member", result.stderr)
        self.assertEqual(outside.read_text(), "keep outside")
        self.assertFalse((self.home / ".local/bin/starship").exists())

    def test_other_archive_members_are_never_extracted(self):
        archive_path = self.fixtures / "starship.tar.gz"
        self.make_archive(archive_path, {"starship": b"#!/bin/sh\nexit 0\n", "../../escape.txt": b"unexpected"})
        self.rows[0][2] = digest(archive_path.read_bytes())
        self.update_lock()
        temporary = self.base / "tmp"
        temporary.mkdir()
        self.run_installer(TMPDIR=str(temporary))
        self.assertFalse((self.base / "escape.txt").exists())
        self.assertEqual(list(temporary.iterdir()), [])

    def test_deleting_repository_keeps_all_installed_files(self):
        self.run_installer()
        before = snapshot(self.home)
        shutil.rmtree(self.repo)
        self.assertEqual(snapshot(self.home), before)
        self.assertFalse(any(path.is_symlink() for path in self.home.rglob("*")))

    def test_audit_hides_detected_value(self):
        synthetic = "ghp_" + "A" * 36
        with (self.repo / "files/.zshrc").open("a") as output:
            output.write("\nexport EXAMPLE_TOKEN=" + synthetic + "\n")
        result = subprocess.run(
            ["/usr/bin/python3", "-B", str(self.repo / "scripts/audit.py")],
            text=True, capture_output=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provider token", result.stdout)
        self.assertNotIn(synthetic, result.stdout + result.stderr)

    def test_kde_merge_preserves_unrelated_preferences(self):
        config = self.home / ".config"
        config.mkdir()
        shortcuts = config / "kglobalshortcutsrc"
        shortcuts.write_text("# local shortcuts\n[kwin]\nWindow Close=Meta+Q,Alt+F4,Close\nSwitch to Desktop 2=Meta+9,none,Local\n\n[services][other.desktop]\n_launch=Meta+Y\n")
        (config / "kcminputrc").write_text("[Mouse]\ncursorTheme=KeepMyCursor\n\n[Keyboard]\nRepeatDelay=999\nOtherKeyboardOption=keep\n")
        (config / "kwinrc").write_text("[Desktops]\nNumber=2\nRows=1\nId_1=keep-id\n\n[Windows]\nBorderSnapZone=17\n")
        self.run_installer()
        self.assertIn("# local shortcuts\n", shortcuts.read_text())
        self.assertIn("Window Close=Meta+Q,Alt+F4,Close", shortcuts.read_text())
        self.assertIn("[services][other.desktop]\n_launch=Meta+Y", shortcuts.read_text())
        self.assertIn("Switch to Desktop 2=Meta+1,", shortcuts.read_text())
        self.assertIn("[services][org.kde.konsole.desktop]\n_launch=Meta+Return", shortcuts.read_text())
        self.assertIn("cursorTheme=KeepMyCursor", (config / "kcminputrc").read_text())
        self.assertIn("OtherKeyboardOption=keep", (config / "kcminputrc").read_text())
        self.assertIn("RepeatDelay=250", (config / "kcminputrc").read_text())
        self.assertIn("Id_1=keep-id", (config / "kwinrc").read_text())
        self.assertIn("BorderSnapZone=17", (config / "kwinrc").read_text())
        self.assertIn("Number=9", (config / "kwinrc").read_text())
        self.assertFalse((self.home / ".local/state/mpv").exists())

    def test_unrelated_shortcut_edits_are_kept_on_reinstall_and_check(self):
        self.run_installer()
        target = self.home / ".config/kglobalshortcutsrc"
        with target.open("a") as output:
            output.write("\n[custom]\nmy-action=Meta+J\n")
        before = snapshot(self.home)
        self.run_installer("--check", FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual(snapshot(self.home), before)

    def test_managed_shortcut_change_is_backed_up(self):
        self.run_installer()
        target = self.home / ".config/kglobalshortcutsrc"
        modified = target.read_text().replace("Switch to Desktop 2=Meta+1,", "Switch to Desktop 2=Meta+9,")
        target.write_text(modified)
        self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertIn("Switch to Desktop 2=Meta+1,", target.read_text())
        backups = list((self.home / ".local/state/dotfiles/backups").glob("*/.config/kglobalshortcutsrc"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), modified)

    def test_merge_handles_nested_sections_and_missing_final_newline(self):
        target = self.base / "targetrc"
        output = self.base / "renderedrc"
        target.write_text("[services][other.desktop]\n_launch=Meta+Y\n[kwin]\nWindow Close=Meta+Q")
        helper = self.repo / "scripts/merge-kconfig.py"
        fragment = self.repo / "files/.config/kglobalshortcutsrc"
        subprocess.run(["/usr/bin/python3", str(helper), "--render", str(fragment), str(target), str(output)], check=True)
        self.assertIn("Window Close=Meta+Q\n", output.read_text())
        self.assertIn("[services][other.desktop]\n_launch=Meta+Y", output.read_text())
        subprocess.run(["/usr/bin/python3", str(helper), "--check", str(fragment), str(output)], check=True)

    def test_conflicting_keys_are_freed_without_removing_other_bindings(self):
        config = self.home / ".config"
        config.mkdir()
        target = config / "kglobalshortcutsrc"
        target.write_text("[kwin]\nShow Desktop=Meta+D,Meta+D,Peek at Desktop\nOther Action=Meta+D\\tAlt+P,none,Other\nModifier Order=Ctrl+Meta+Left,none,Other\nEscaped Comma=Ctrl+K\\,Ctrl+C\\tMeta+D,none,Other\n\n[services][other.desktop]\n_launch=Meta+Return\\tMeta+Y\n")
        self.run_installer()
        text = target.read_text()
        self.assertIn("Show Desktop=none,Meta+D,Peek at Desktop", text)
        self.assertIn("Other Action=Alt+P,none,Other", text)
        self.assertIn("Modifier Order=none,none,Other", text)
        self.assertIn("Escaped Comma=Ctrl+K\\,Ctrl+C,none,Other", text)
        self.assertIn("[services][other.desktop]\n_launch=Meta+Y", text)
        self.assertIn("[services][org.kde.konsole.desktop]\n_launch=Meta+Return", text)
        self.run_installer("--check")


if __name__ == "__main__":
    unittest.main()
