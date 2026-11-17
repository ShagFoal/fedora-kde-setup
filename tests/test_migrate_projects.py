import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
spec = importlib.util.spec_from_file_location('migration_links', SCRIPTS / 'links.py')
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='projects-bind-test-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.home = self.base / 'home'
        self.source = self.home / 'Main/Projects'
        self.target = self.home / 'Projects'
        self.source.mkdir(parents=True)
        self.target.mkdir()
        (self.target / 'underlying.txt').write_text('original')
        (self.source / 'project.txt').write_text('main')
        configs = self.home / 'Main' / links.CONFIG_DIRECTORY
        for relative in links.CONFIG_FILES.values():
            path = configs / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# fixture\n')
        (configs / '.ssh').mkdir(mode=0o700)
        self.fstab = self.base / 'fstab'
        self.base_table = '# user table\nUUID=fixture / btrfs defaults 0 0\n'
        self.record = f'{self.source} {self.target} none bind,nofail,x-systemd.requires-mounts-for={self.source} 0 0\n'
        self.fstab.write_text(self.base_table + self.record)
        self.backup = self.base / f'fstab.before-projects-link-{os.getuid()}'
        self.script = self.base / 'migrate-projects-bind.sh'
        # Only the disposable copy operates on the test table.
        self.script.write_text((SCRIPTS / self.script.name).read_text().replace('fstab=/etc/fstab', 'fstab=' + str(self.fstab)))
        shutil.copy2(SCRIPTS / 'links.py', self.base / 'links.py')
        sudo = self.base / 'sudo'
        sudo.write_text("""#!/bin/sh
set -eu
case "$1" in
  systemctl) test "$2" = daemon-reload; test -z "${FAIL_RELOAD:-}" ;;
  mktemp|mv|tee|umount|ln|cp|rm) exec "$@" ;;
  *) exit 99 ;;
esac
""")
        sudo.chmod(0o755)
        self.env = dict(os.environ, HOME=str(self.home), PATH=f'{self.base}:/usr/bin:/bin',
                        SCRIPT=str(self.script), SOURCE=str(self.source), TARGET=str(self.target))
        for name in ('XDG_CONFIG_HOME', 'XDG_STATE_HOME', 'XDG_DATA_HOME', 'ZDOTDIR', 'STARSHIP_CONFIG'):
            self.env.pop(name, None)

    def execute(self, *args):
        return subprocess.run(['bash', str(self.script), *args], env=self.env,
                              cwd=self.base, capture_output=True, text=True, timeout=10)

    def mounted(self, scenario):
        # An actual bind in a private mount/user namespace. The host mount table,
        # system manager and sudo credentials are never touched.
        if not shutil.which('unshare'):
            self.skipTest('unshare is required for the bind mount fixture')
        command = ['unshare', '--user', '--map-current-user', '--keep-caps', '--mount', '--']
        probe = subprocess.run(command + ['true'], capture_output=True)
        if probe.returncode:
            self.skipTest('unprivileged user/mount namespaces unavailable')
        result = subprocess.run(command + ['bash', '-ec', scenario], env=self.env,
                                cwd=self.base, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_migration_of_unmounted_record_and_rerun(self):
        result = self.execute()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.backup.read_text(), self.base_table + self.record)
        self.assertEqual(self.fstab.read_text(), self.base_table)
        self.assertEqual(self.target.resolve(), self.source)
        backups = list((self.home / '.local/state/dotfiles/backups').glob('*/Projects/underlying.txt'))
        self.assertEqual([path.read_text() for path in backups], ['original'])
        self.assertEqual(self.execute().returncode, 0)
        self.assertEqual(self.backup.read_text(), self.base_table + self.record)

    def test_refuses_duplicate_or_foreign_entries(self):
        for row in (self.record + self.record, self.record.replace(str(self.source) + ' ', '/elsewhere '),
                    self.record.replace('bind,nofail', 'rbind,nofail'), ''):
            with self.subTest(row=row):
                self.fstab.write_text(self.base_table + row)
                self.assertNotEqual(self.execute().returncode, 0)
                self.assertEqual(self.fstab.read_text(), self.base_table + row)
                self.assertFalse(self.backup.exists())
                self.assertFalse(self.target.is_symlink())

    def test_busy_mount_preserves_fstab_and_mount(self):
        self.mounted("""
mount --bind "$SOURCE" "$TARGET"
bash "$SCRIPT" --dry-run
cd "$TARGET"
if bash "$SCRIPT"; then exit 1; fi
mountpoint -q "$TARGET"
""")
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.fstab.read_text(), self.base_table + self.record)
        self.assertEqual(list(self.base.glob('.fstab-projects.*')), [])

    def test_unmount_and_resume_after_reload_failure(self):
        self.mounted("""
mount --bind "$SOURCE" "$TARGET"
if FAIL_RELOAD=1 bash "$SCRIPT"; then exit 1; fi
test -d "$TARGET" && ! test -L "$TARGET"
! mountpoint -q "$TARGET"
bash "$SCRIPT"
test -L "$TARGET"
""")
        self.assertEqual(self.target.resolve(), self.source)
        self.assertEqual(self.fstab.read_text(), self.base_table)
        self.assertEqual(self.backup.read_text(), self.base_table + self.record)

    def test_refuses_mounted_foreign_directory(self):
        foreign = self.home / 'other'
        foreign.mkdir()
        self.mounted("""
mount --bind "$HOME/other" "$TARGET"
if bash "$SCRIPT"; then exit 1; fi
mountpoint -q "$TARGET"
""")
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.fstab.read_text(), self.base_table + self.record)


if __name__ == '__main__':
    unittest.main()
