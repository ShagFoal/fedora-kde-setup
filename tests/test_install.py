import hashlib
import io
import importlib.util
import os
import pty
import select
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("installer_links", ROOT / "scripts/links.py")
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)
CONFIGS = [
    ".zshrc", ".config/starship.toml", ".config/konsolerc",
    ".local/share/konsole/Profile 1.profile",
    ".local/share/konsole/Catppuccin-Mocha.colorscheme",
    ".config/fastfetch/config.jsonc",
    ".config/dolphinrc",
    ".local/share/kxmlgui5/dolphin/dolphinui.rc",
    ".config/mpv/mpv.conf",
]
MOCK = '''#!/usr/bin/python3
import os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(name + '\\n')
marker = pathlib.Path(os.environ['PACKAGE_MARKER'])
if name == 'rpm':
    missing = os.environ.get('MOCK_MISSING_PACKAGES', 'zsh').split(',')
    sys.exit(1 if sys.argv[-1] in missing and not marker.exists() else 0)
if name == 'sudo':
    assert not os.environ.get('FORBID_SUDO'), 'Unexpected sudo'
    assert sys.argv[1:4] == ['dnf', 'install', '-y']
    assert 'mpv' not in sys.argv[4:], 'MPV must be installed by the user'
    for required in os.environ.get('REQUIRED_PACKAGES', '').split(','):
        assert not required or required in sys.argv[4:]
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
        self.sources = self.home / "Main" / links.CONFIG_DIRECTORY
        for relative in CONFIGS:
            source = self.sources / links.CONFIG_FILES[relative]
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# fixture config\n")
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

    def test_dry_run_has_no_changes_or_network(self):
        before = snapshot(self.home)
        self.run_installer("--dry-run", FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual(snapshot(self.home), before)
        self.assertTrue(all(name == "rpm" for name in self.calls()))

    def test_installs_dependencies_and_links_from_main(self):
        old = self.home / ".zshrc"
        old.write_text("original config\n")
        old.chmod(0o600)
        self.run_installer()
        for relative in CONFIGS:
            target = self.home / relative
            self.assertTrue(target.is_symlink(), relative)
            self.assertEqual(target.resolve(), self.sources / links.CONFIG_FILES[relative])
        backups = list((self.home / ".local/state/dotfiles/backups").glob("*/.zshrc"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "original config\n")
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        before = snapshot(self.home)
        self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual(snapshot(self.home), before)
        self.run_installer("--check")

    def test_config_changes_in_main_are_kept_and_check_passes(self):
        self.run_installer()
        (self.home / ".config/starship.toml").write_text("# changed live config\n")
        self.assertEqual((self.sources / links.CONFIG_FILES[".config/starship.toml"]).read_text(), "# changed live config\n")
        self.run_installer("--check")
        self.run_installer(FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertEqual((self.sources / links.CONFIG_FILES[".config/starship.toml"]).read_text(), "# changed live config\n")

    def test_links_only_does_not_install_or_download(self):
        self.run_installer("--links-only", FORBID_DOWNLOAD="1", FORBID_SUDO="1")
        self.assertNotIn("curl", self.calls())
        self.assertNotIn("sudo", self.calls())
        self.assertTrue((self.home / ".zshrc").is_symlink())

    def test_missing_main_config_stops_before_packages(self):
        (self.sources / links.CONFIG_FILES[".config/starship.toml"]).unlink()
        before = snapshot(self.home)
        self.run_installer(success=False)
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn("sudo", self.calls())

    def test_corrupt_download_does_not_replace_live_configs(self):
        (self.home / ".zshrc").write_text("keep me")
        self.run_installer(success=False, CORRUPT_DOWNLOAD="1")
        self.assertEqual((self.home / ".zshrc").read_text(), "keep me")

    def test_config_parent_symlink_is_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.home / ".config").symlink_to(outside, target_is_directory=True)
        self.run_installer(success=False)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertNotIn("sudo", self.calls())

    def test_manifest_tamper_stops_before_changes(self):
        with (self.repo / "dependencies.tsv").open("a") as output:
            output.write("# changed\n")
        before = snapshot(self.home)
        self.run_installer("--dry-run", success=False)
        self.assertEqual(snapshot(self.home), before)

    def test_deleting_bootstrap_repo_keeps_main_config_links(self):
        self.run_installer()
        shutil.rmtree(self.repo)
        for relative in CONFIGS:
            self.assertTrue((self.home / relative).is_symlink())
            self.assertEqual((self.home / relative).read_text(), "# fixture config\n")

    def test_directory_target_is_rejected_before_install(self):
        (self.home / ".zshrc").mkdir()
        self.run_installer(success=False)
        self.assertNotIn("sudo", self.calls())

    def test_xdg_paths_inside_home(self):
        self.env.update(XDG_CONFIG_HOME=str(self.home / "settings"), XDG_DATA_HOME=str(self.home / "data"), XDG_STATE_HOME=str(self.home / "state"), ZDOTDIR=str(self.home / "shell"))
        self.run_installer()
        self.assertEqual((self.home / "settings/starship.toml").resolve(), self.sources / links.CONFIG_FILES[".config/starship.toml"])
        self.assertEqual((self.home / "shell/.zshrc").resolve(), self.sources / links.CONFIG_FILES[".zshrc"])
        self.run_installer("--check")

    def test_restic_and_rclone_are_installed_if_missing(self):
        self.run_installer(MOCK_MISSING_PACKAGES="restic,rclone", REQUIRED_PACKAGES="restic,rclone")
        self.assertIn("sudo", self.calls())

    def test_restore_requires_terminal_before_changes(self):
        before = snapshot(self.home)
        self.run_installer("--restore", success=False)
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn("sudo", self.calls())

    def test_restore_mode_precedes_linking(self):
        shutil.rmtree(self.home / "Main")
        helper = self.repo / "scripts/restore.py"
        helper.write_text("from pathlib import Path\nimport os,sys\nfrom links import CONFIGS,CONFIG_DIRECTORY,CONFIG_FILES\nassert sys.argv[2]=='--activate-main'\nroot=Path(os.environ['HOME'])/'Main'/CONFIG_DIRECTORY\nfor relative in CONFIGS:\n p=root/CONFIG_FILES[relative]\n p.parent.mkdir(parents=True,exist_ok=True)\n p.write_text('# restored config\\n')\n")
        self.update_lock()
        master, slave = pty.openpty()
        child = subprocess.Popen(["bash", str(self.repo / "install.sh"), "--restore"], env=self.env, cwd=self.base, stdin=slave, stdout=slave, stderr=slave)
        os.close(slave)
        output = bytearray()
        started = time.monotonic()
        try:
            while child.poll() is None:
                if time.monotonic() - started > 30:
                    child.kill()
                    self.fail("Interactive test exceeded 30 seconds")
                if select.select([master], [], [], 0.1)[0]:
                    try:
                        output.extend(os.read(master, 65536))
                    except OSError:
                        break
            self.assertEqual(child.wait(timeout=5), 0, output.decode(errors="replace"))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            os.close(master)
        self.assertTrue((self.home / ".zshrc").is_symlink())
        self.assertEqual((self.home / ".zshrc").read_text(), "# restored config\n")

    def test_archive_symlink_is_rejected(self):
        archive_path = self.fixtures / "starship.tar.gz"
        with tarfile.open(archive_path, "w:gz") as archive:
            link = tarfile.TarInfo("starship")
            link.type = tarfile.SYMTYPE
            link.linkname = str(self.base / "outside")
            archive.addfile(link)
        self.rows[0][2] = digest(archive_path.read_bytes())
        self.update_lock()
        self.run_installer(success=False)
        self.assertFalse((self.home / ".zshrc").exists())

    def test_other_archive_paths_are_never_extracted(self):
        path = self.fixtures / "starship.tar.gz"
        self.make_archive(path, {"starship": b"#!/bin/sh\nexit 0\n", "../../escape.txt": b"unexpected"})
        self.rows[0][2] = digest(path.read_bytes())
        self.update_lock()
        temporary = self.base / "tmp"
        temporary.mkdir()
        self.run_installer(TMPDIR=str(temporary))
        self.assertFalse((self.base / "escape.txt").exists())
        self.assertEqual(list(temporary.iterdir()), [])

    def test_audit_hides_detected_value(self):
        synthetic = "ghp_" + "A" * 36
        with (self.repo / "README.md").open("a") as output:
            output.write("\n" + synthetic + "\n")
        result = subprocess.run(["/usr/bin/python3", "-B", str(self.repo / "scripts/audit.py")], text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("provider token", result.stdout)
        self.assertNotIn(synthetic, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
