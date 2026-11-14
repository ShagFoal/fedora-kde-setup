import hashlib
import io
import importlib.util
import json
import os
import pty
import select
from pathlib import Path
import shutil
import subprocess
import sys
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
import json, os, pathlib, shutil, sys
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['CALL_LOG'], 'a') as log:
    log.write(name + '\\n')
with open(os.environ['COMMAND_LOG'], 'a') as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
marker = pathlib.Path(os.environ['PACKAGE_MARKER'])
if name in ('rpm', 'dpkg-query'):
    package = sys.argv[-1]
    if package == 'kubuntu-settings-desktop' and os.environ.get('MOCK_NO_KUBUNTU'):
        sys.exit(1)
    missing = os.environ.get('MOCK_MISSING_PACKAGES', 'zsh').split(',')
    if package in missing and not marker.exists():
        if name == 'dpkg-query' and os.environ.get('MOCK_DPKG_MISSING_STATUS'):
            print(os.environ['MOCK_DPKG_MISSING_STATUS'], end='')
            sys.exit(0)
        sys.exit(1)
    if name == 'dpkg-query':
        assert sys.argv[1:3] == ['-W', '-f=${Status}']
        print(os.environ.get('MOCK_DPKG_STATUS', 'install ok installed'), end='')
    sys.exit(0)
if name == 'sudo':
    assert not os.environ.get('FORBID_SUDO'), 'Unexpected sudo'
    assert sys.argv[1] == os.environ['MOCK_PACKAGE_MANAGER']
    if sys.argv[1] == 'apt-get':
        if sys.argv[2:] == ['-o', 'APT::Update::Error-Mode=any', 'update']:
            sys.exit(100 if os.environ.get('MOCK_APT_UPDATE_FAILURE') else 0)
        assert sys.argv[2:6] == ['install', '-y', '--no-remove', '--no-install-recommends']
        packages = sys.argv[6:]
    else:
        assert sys.argv[1:4] == ['dnf', 'install', '-y']
        packages = sys.argv[4:]
    assert 'mpv' not in packages, 'MPV must be installed by the user'
    for required in os.environ.get('REQUIRED_PACKAGES', '').split(','):
        assert not required or required in packages
    if os.environ.get('MOCK_INSTALL_FAILURE'):
        sys.exit(100)
    if not os.environ.get('MOCK_LEAVE_PACKAGES_MISSING'):
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


class AuditTests(unittest.TestCase):
    def test_google_oauth_values_are_rejected_without_disclosure_or_writes(self):
        samples = [
            "GOC" + "SPX-" + "a" * 28,
            "123456789-" + "b" * 24 + ".apps.googleusercontent.com",
            "ya" + "29." + "c" * 40,
        ]
        with tempfile.TemporaryDirectory(prefix="audit-test-") as temporary:
            repo = Path(temporary) / "repo"
            shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            original = (repo / "README.md").read_text()
            for value in samples:
                with self.subTest(prefix=value[:5]):
                    (repo / "README.md").write_text(original + '\n{"credential": "' + value + '"}\n')
                    files = sorted(p for p in repo.rglob("*") if p.is_file() and p.name != "SHA256SUMS")
                    (repo / "SHA256SUMS").write_text("".join(f"{digest(p.read_bytes())}  {p.relative_to(repo).as_posix()}\n" for p in files))
                    before = snapshot(repo)
                    result = subprocess.run([sys.executable, "-B", str(repo / "scripts/audit.py")], text=True, capture_output=True, timeout=15)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn("value hidden", result.stdout)
                    self.assertNotIn(value, result.stdout + result.stderr)
                    self.assertEqual(snapshot(repo), before)


class InstallerTests(unittest.TestCase):
    entrypoint = 'install.sh'
    os_release_contents = 'ID=fedora\nVERSION_ID=45\n'
    query_command = 'rpm'
    package_manager = 'dnf'

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dotfiles-test-")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "repo"
        shutil.copytree(ROOT, self.repo, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        # Substitute only inside the temporary checkout; production always reads /etc/os-release.
        self.os_release = self.base / "os-release"
        self.os_release.write_text(self.os_release_contents)
        engine = self.repo / "scripts/install-common.sh"
        engine.write_text(engine.read_text().replace('/etc/os-release', str(self.os_release)))
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
        self.command_log = self.base / "commands"
        for name in ["rpm", "dpkg-query", "sudo", "dnf", "apt-get", "curl", "fc-cache", "zsh"]:
            command = self.bin / name
            command.write_text(MOCK)
            command.chmod(0o755)
        self.env = dict(os.environ)
        for name in ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "ZDOTDIR", "STARSHIP_CONFIG", "BASH_ENV", "ENV"]:
            self.env.pop(name, None)
        self.env.update(
            HOME=str(self.home), PATH=f"{self.bin}:/usr/bin:/bin",
            CALL_LOG=str(self.log), PACKAGE_MARKER=str(self.base / "packages-installed"),
            COMMAND_LOG=str(self.command_log), MOCK_PACKAGE_MANAGER=self.package_manager,
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
            ["bash", str(self.repo / self.entrypoint), *args], cwd=self.base,
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
        self.assertTrue(all(name == self.query_command for name in self.calls()))

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

    def test_wrong_os_or_release_stops_before_package_manager_or_home_changes(self):
        for contents in ('ID=debian\nVERSION_ID=26.10\n', 'ID=ubuntu\nVERSION_ID=26.04\n'):
            with self.subTest(contents=contents):
                self.os_release.write_text(contents)
                before = snapshot(self.home)
                self.run_installer(success=False)
                self.assertEqual(snapshot(self.home), before)
                self.assertEqual(self.calls(), [])

    def test_check_fails_without_writing_or_installing_when_packages_are_missing(self):
        self.run_installer()
        (self.base / 'packages-installed').unlink()
        before = snapshot(self.home)
        result = self.run_installer('--check', success=False, FORBID_SUDO='1', FORBID_DOWNLOAD='1')
        self.assertIn('Missing', result.stdout)
        self.assertEqual(snapshot(self.home), before)

    def test_failed_package_install_keeps_existing_configs(self):
        target = self.home / '.zshrc'
        target.write_text('keep original config')
        self.run_installer(success=False, MOCK_INSTALL_FAILURE='1')
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), 'keep original config')
        self.assertNotIn('curl', self.calls())

    def test_packages_are_verified_after_install(self):
        self.run_installer(success=False, MOCK_LEAVE_PACKAGES_MISSING='1')
        self.assertNotIn('curl', self.calls())
        self.assertFalse((self.home / '.zshrc').exists())

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

    def test_shared_implementation_is_verified_before_execution(self):
        engine = self.repo / 'scripts/install-common.sh'
        engine.write_text('printf unexpected > "$HOME/executed"\n' + engine.read_text())
        before = snapshot(self.home)
        self.run_installer('--dry-run', success=False)
        self.assertEqual(snapshot(self.home), before)
        self.assertEqual(self.calls(), [])

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
        child = subprocess.Popen(["bash", str(self.repo / self.entrypoint), "--restore"], env=self.env, cwd=self.base, stdin=slave, stdout=slave, stderr=slave)
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


class KubuntuInstallerTests(InstallerTests):
    entrypoint = 'install-kubuntu.sh'
    os_release_contents = 'ID=ubuntu\nVERSION_ID=26.10\n'
    query_command = 'dpkg-query'
    package_manager = 'apt-get'

    def test_apt_refreshes_indexes_then_installs_only_missing_packages_without_removals(self):
        self.run_installer(MOCK_MISSING_PACKAGES='fastfetch,ca-certificates')
        commands = [json.loads(line) for line in self.command_log.read_text().splitlines()]
        privileged = [command for command in commands if command[0] == 'sudo']
        self.assertEqual(privileged, [
            ['sudo', 'apt-get', '-o', 'APT::Update::Error-Mode=any', 'update'],
            ['sudo', 'apt-get', 'install', '-y', '--no-remove', '--no-install-recommends', 'fastfetch', 'ca-certificates'],
        ])
        self.assertNotIn('rpm', self.calls())
        self.assertNotIn('dnf', self.calls())

    def test_minimal_installation_gets_all_required_packages_without_full_desktop(self):
        missing = [
            'zsh', 'konsole', 'fastfetch', 'dolphin', 'git', 'curl', 'python3',
            'fontconfig', 'util-linux', 'restic', 'rclone', 'ca-certificates',
            'diffutils', 'gh', 'openssh-client', 'xdg-utils',
        ]
        self.run_installer(MOCK_MISSING_PACKAGES=','.join(missing))
        commands = [json.loads(line) for line in self.command_log.read_text().splitlines()]
        installs = [command for command in commands if command[:3] == ['sudo', 'apt-get', 'install']]
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0][3:6], ['-y', '--no-remove', '--no-install-recommends'])
        self.assertEqual(installs[0][6:], missing)
        self.assertTrue((self.home / '.zshrc').is_symlink())
        self.run_installer('--check')

    def test_minimal_desktop_does_not_require_kubuntu_desktop_metapackage(self):
        # Calamares Minimal may omit the full-desktop metapackage while keeping settings.
        self.run_installer('--dry-run', MOCK_MISSING_PACKAGES='kubuntu-desktop', FORBID_SUDO='1', FORBID_DOWNLOAD='1')
        self.assertNotIn('sudo', self.calls())
        commands = [json.loads(line) for line in self.command_log.read_text().splitlines()]
        queried = [command[-1] for command in commands if command[0] == 'dpkg-query']
        self.assertNotIn('kubuntu-desktop', queried)

    def test_missing_python_is_bootstrapped_before_config_helpers_run(self):
        # Only the temporary checkout hides Python until the mock APT install succeeds.
        # No production environment variable can skip real OS or dependency checks.
        engine = self.repo / 'scripts/install-common.sh'
        shim = '''command() {
  if [[ "$*" = '-v python3' && ! -f "$PACKAGE_MARKER" ]]; then
    return 1
  fi
  builtin command "$@"
}
python3() {
  [[ -f "$PACKAGE_MARKER" ]] || { printf 'Python ran before installation\\n' >&2; return 1; }
  /usr/bin/python3 "$@"
}
'''
        engine.write_text(shim + engine.read_text())
        self.update_lock()
        self.run_installer(MOCK_MISSING_PACKAGES='python3', REQUIRED_PACKAGES='python3')
        self.assertTrue((self.home / '.zshrc').is_symlink())

    def test_apt_update_failure_prevents_downloads_and_live_config_changes(self):
        target = self.home / '.zshrc'
        target.write_text('keep original config')
        self.run_installer(success=False, MOCK_APT_UPDATE_FAILURE='1')
        self.assertEqual(self.calls().count('sudo'), 1)
        self.assertNotIn('curl', self.calls())
        self.assertFalse(target.is_symlink())
        self.assertEqual(target.read_text(), 'keep original config')

    def test_plain_ubuntu_without_kubuntu_settings_is_rejected(self):
        before = snapshot(self.home)
        result = self.run_installer(success=False, MOCK_NO_KUBUNTU='1')
        self.assertIn('Kubuntu desktop settings are missing', result.stderr)
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn('sudo', self.calls())

    def test_held_installed_packages_do_not_trigger_apt(self):
        self.run_installer('--dry-run', MOCK_MISSING_PACKAGES='', MOCK_DPKG_STATUS='hold ok installed', FORBID_SUDO='1')
        self.assertNotIn('sudo', self.calls())

    def test_residual_config_and_unconfigured_packages_are_installed(self):
        for status in ('deinstall ok config-files', 'install ok unpacked', 'install ok half-configured'):
            with self.subTest(status=status):
                marker = self.base / 'packages-installed'
                marker.unlink(missing_ok=True)
                self.run_installer(MOCK_DPKG_MISSING_STATUS=status, REQUIRED_PACKAGES='zsh')
                self.assertTrue(marker.exists())

    def test_kubuntu_id_is_accepted_as_well_as_ubuntu_id(self):
        self.os_release.write_text('ID=kubuntu\nVERSION_ID=26.10\n')
        self.run_installer('--dry-run', FORBID_SUDO='1', FORBID_DOWNLOAD='1')

    def test_restore_never_replaces_existing_main(self):
        # With a terminal, the existing-Main guard precedes any sudo or restoration.
        # The shared restore helper also has an independent existing-Main guard.
        helper = self.repo / 'scripts/restore.py'
        helper.write_text("raise AssertionError('Restore must not run with existing Main')\n")
        self.update_lock()
        master, slave = pty.openpty()
        before = snapshot(self.home)
        try:
            result = subprocess.run(
                ['bash', str(self.repo / self.entrypoint), '--restore'],
                env=self.env, cwd=self.base, stdin=slave, stdout=slave, stderr=slave, timeout=10,
            )
        finally:
            os.close(slave)
            os.close(master)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn('sudo', self.calls())


if __name__ == "__main__":
    unittest.main()
