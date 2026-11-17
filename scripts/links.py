#!/usr/bin/env python3
"""Link restored Main files and directories into the user profile."""
import ctypes
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import uuid


CONFIGS = (
    ".zshrc",
    ".config/starship.toml",
    ".config/konsolerc",
    ".local/share/konsole/Profile 1.profile",
    ".local/share/konsole/Catppuccin-Mocha.colorscheme",
    ".config/fastfetch/config.jsonc",
    ".config/dolphinrc",
    ".local/share/kxmlgui5/dolphin/dolphinui.rc",
    ".config/mpv/mpv.conf",
)
CONFIG_DIRECTORY = Path("System/Configs")
LEGACY_DIRECTORY = Path("Configs/Dotfiles")
CONFIG_FILES = {
    ".zshrc": "zsh/zshrc",
    ".config/starship.toml": "starship/starship.toml",
    ".config/konsolerc": "konsole/konsolerc",
    ".local/share/konsole/Profile 1.profile": "konsole/Profile 1.profile",
    ".local/share/konsole/Catppuccin-Mocha.colorscheme": "konsole/Catppuccin-Mocha.colorscheme",
    ".config/fastfetch/config.jsonc": "fastfetch/config.jsonc",
    ".config/dolphinrc": "dolphin/dolphinrc",
    ".local/share/kxmlgui5/dolphin/dolphinui.rc": "dolphin/dolphinui.rc",
    ".config/mpv/mpv.conf": "mpv/mpv.conf",
}


class LinkError(Exception):
    pass


def normal_home(value=None):
    home = Path(value or os.environ.get("HOME", ""))
    if not home.is_absolute() or home == Path("/") or not home.is_dir() or home != home.resolve():
        raise LinkError("Нужна существующая абсолютная домашняя папка без ссылок.")
    return home


def directory_chain(path):
    while path != path.parent:
        if path.is_symlink():
            raise LinkError(f"Ссылка вместо каталога: {path}")
        if path.exists() and not path.is_dir():
            raise LinkError(f"Ожидался каталог: {path}")
        path = path.parent


def user_directory(home, variable, fallback):
    value = Path(os.environ.get(variable) or str(home / fallback))
    if not value.is_absolute() or not value.is_relative_to(home) or ".." in value.parts:
        raise LinkError(f"{variable} должен находиться внутри домашней папки.")
    directory_chain(value)
    return value


def validate_ssh(directory):
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise LinkError(f"Каталог SSH должен принадлежать пользователю и иметь права 0700: {directory}")
    for item in directory.iterdir():
        if item.name.startswith("id_") and not item.name.endswith(".pub"):
            if item.is_file() and item.stat().st_mode & 0o077:
                raise LinkError(f"Закрой доступ группы и остальных к ключу: {item}")
        elif item.name in {"config", "authorized_keys"} and item.stat().st_mode & 0o022:
            raise LinkError(f"Убери право записи группы и остальных: {item}")


def plan(home=None, main_root=None, sources=True):
    home = normal_home(home)
    config = user_directory(home, "XDG_CONFIG_HOME", ".config")
    data = user_directory(home, "XDG_DATA_HOME", ".local/share")
    zsh = user_directory(home, "ZDOTDIR", "")
    state = user_directory(home, "XDG_STATE_HOME", ".local/state")
    for base in (config, data, zsh, state):
        if base.is_relative_to(home / ".ssh") or base.is_relative_to(home / "Projects"):
            raise LinkError(f"Путь настроек находится внутри заменяемого каталога: {base}")
    if os.environ.get("STARSHIP_CONFIG", str(config / "starship.toml")) != str(config / "starship.toml"):
        raise LinkError("STARSHIP_CONFIG указывает на другой файл.")
    main = Path(main_root) if main_root is not None else home / "Main"
    root = main / CONFIG_DIRECTORY
    layout = CONFIG_FILES
    if not os.path.lexists(root) and os.path.lexists(main / LEGACY_DIRECTORY):
        root = main / LEGACY_DIRECTORY
        layout = {relative: relative for relative in CONFIGS}
    entries = []
    for relative in CONFIGS:
        source = root / layout[relative]
        if sources:
            directory_chain(source.parent)
            if source.is_symlink() or not source.is_file():
                raise LinkError(f"Нет обычного конфига {source}. Сначала восстанови Main с настройками.")
        if relative == ".zshrc":
            target = zsh / ".zshrc"
        elif relative.startswith(".config/"):
            target = config / relative[len(".config/"):]
        else:
            target = data / relative[len(".local/share/"):]
        directory_chain(target.parent)
        if target.exists() and not target.is_file() and not target.is_symlink():
            raise LinkError(f"Ожидался файл или ссылка: {target}")
        entries.append((source, target))
    for source, target in ((root / ".ssh", home / ".ssh"), (main / "Projects", home / "Projects")):
        # Older snapshots can predate one or both directory links.
        if root == main / LEGACY_DIRECTORY and not os.path.lexists(source):
            continue
        if sources:
            directory_chain(source)
            if not source.is_dir():
                raise LinkError(f"Нет каталога {source}. Восстанови его из Main.")
            if target == home / ".ssh":
                validate_ssh(source)
        if os.path.lexists(target) and not (target.is_symlink() or target.is_dir() or target.is_file()):
            raise LinkError(f"Ожидался каталог, обычный файл или ссылка: {target}")
        entries.append((source, target))
    return entries


def mount_points():
    # mountinfo includes same-filesystem bind mounts and escapes whitespace and backslashes.
    paths = set()
    with open("/proc/self/mountinfo", "rb") as table:
        for line in table:
            field = os.fsdecode(line.split(b" ")[4])
            paths.add(Path(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), field)))
    return paths


def mount_conflict(source, target, mounts):
    if target.is_symlink():
        return None
    if target in mounts:
        if target.name == "Projects" and source.is_dir() and source.samefile(target):
            return f"{target} — bind mount Main/Projects. Для перехода на ссылку запусти bash scripts/migrate-projects-bind.sh"
        return f"{target} — точка монтирования. Перед заменой отключи её и проверь /etc/fstab."
    if target.is_dir():
        for mount in mounts:
            if target in mount.parents:
                return f"Внутри {target} найдена точка монтирования {mount}. Размонтируй её перед переносом каталога."
    return None


def check_mounts(entries):
    mounts = mount_points()
    for source, target in entries:
        conflict = mount_conflict(source, target, mounts)
        if conflict:
            raise LinkError(conflict)


def correct_link(source, target):
    return target.is_symlink() and Path(os.path.realpath(target)) == source


def apply(home=None):
    home = normal_home(home)
    fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return apply_links(home)
    finally:
        os.close(fd)


def apply_links(home):
    entries = plan(home)
    check_mounts(entries)
    state = user_directory(home, "XDG_STATE_HOME", ".local/state")
    backup_root = state / "dotfiles/backups"
    directory_chain(backup_root)
    backup = None
    completed = []
    try:
        for source, target in entries:
            if correct_link(source, target):
                continue
            saved = None
            move_directory = not target.is_symlink() and target.is_dir()
            if os.path.lexists(target):
                if backup is None:
                    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    # Directories must be renamed on the same filesystem, including large project trees.
                    if backup_root.stat().st_dev != home.stat().st_dev and any(
                        dest.is_dir() and not dest.is_symlink() for _, dest in entries
                    ):
                        backup_root = home
                        stamp = ".dotfiles-backup-" + stamp
                    backup = Path(tempfile.mkdtemp(prefix=stamp + "-links-", dir=backup_root))
                    print(f"Резервная копия: {backup}", flush=True)
                saved = backup / target.relative_to(home)
                saved.parent.mkdir(parents=True, exist_ok=True)
                if not move_directory:
                    shutil.copy2(target, saved, follow_symlinks=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(".dotfiles-link-" + uuid.uuid4().hex)
            try:
                temporary.symlink_to(source)
                if move_directory:
                    os.rename(target, saved)
                try:
                    os.replace(temporary, target)
                except BaseException:
                    if move_directory and not os.path.lexists(target):
                        os.rename(saved, target)
                    raise
            finally:
                if temporary.is_symlink():
                    temporary.unlink()
            completed.append((source, target, saved))
            print(f"LINK: {target} -> {source}")
    except BaseException:
        for source, target, saved in reversed(completed):
            if correct_link(source, target):
                target.unlink()
                if saved is not None:
                    if not saved.is_symlink() and saved.is_dir():
                        os.rename(saved, target)
                    else:
                        shutil.copy2(saved, target, follow_symlinks=False)
        raise
    print(f"Ссылок создано: {len(completed)}. Backup: {backup or 'не понадобился'}")
    return backup


def adopt_main(restored, home=None, *, require_configs=True):
    home = normal_home(home)
    restored = Path(restored)
    target = home / "Main"
    if os.path.lexists(target):
        raise LinkError("Main уже существует: восстановленная копия оставлена отдельно, без замены данных.")
    if not restored.is_relative_to(home) or restored.is_symlink() or not restored.is_dir():
        raise LinkError("Неверная папка восстановленного Main.")
    if require_configs:
        plan(home, main_root=restored)
    report = restored.parent
    restored.chmod(0o700)
    # Linux renameat2 with RENAME_NOREPLACE also protects an empty Main created
    # after the preflight. os.rename would replace that directory.
    at_fdcwd, rename_noreplace = -100, 1
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(at_fdcwd, os.fsencode(restored), at_fdcwd, os.fsencode(target), rename_noreplace) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)
    if report.name.startswith("Restored-Main-"):
        marker = report / ".RESTORE_COMPLETE"
        if marker.is_file() and not marker.is_symlink():
            marker.unlink()
        try:
            report.rmdir()
        except OSError:
            pass
    return target


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    if mode not in {"--apply", "--check", "--dry-run", "--validate", "--destinations-only", "--zsh-config"}:
        raise LinkError("Использование: links.py --apply | --check | --dry-run | --validate | --destinations-only | --zsh-config")
    if mode == "--apply":
        apply()
        return
    entries = plan(sources=mode not in {"--destinations-only", "--zsh-config"})
    if mode in {"--destinations-only", "--validate"}:
        check_mounts(entries)
    elif mode == "--check":
        wrong = [target for source, target in entries if not correct_link(source, target)]
        if wrong:
            raise LinkError("Неверные или отсутствующие ссылки: " + ", ".join(str(target) for target in wrong))
        print(f"LINK CHECK PASSED: {len(entries)} ссылок в Main.")
    elif mode == "--zsh-config":
        print(entries[0][0])
    elif mode == "--dry-run":
        mounts = mount_points()
        for source, target in entries:
            conflict = mount_conflict(source, target, mounts)
            if conflict:
                print(conflict)
                continue
            if correct_link(source, target):
                action = "Unchanged link"
            else:
                action = "Link (backup if present)"
            print(f"{action}: {target} -> {source}")


if __name__ == "__main__":
    try:
        main()
    except (LinkError, OSError) as error:
        print("Ошибка ссылок: " + str(error), file=sys.stderr)
        sys.exit(1)
