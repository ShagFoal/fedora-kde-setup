#!/usr/bin/env python3
"""Link restored Main configs into the user profile, preserving replaced files."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
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


def plan(home=None, main_root=None, sources=True):
    home = normal_home(home)
    config = user_directory(home, "XDG_CONFIG_HOME", ".config")
    data = user_directory(home, "XDG_DATA_HOME", ".local/share")
    zsh = user_directory(home, "ZDOTDIR", "")
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
    return entries


def correct_link(source, target):
    return target.is_symlink() and Path(os.path.realpath(target)) == source


def apply(home=None):
    home = normal_home(home)
    entries = plan(home)
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
            if os.path.lexists(target):
                if backup is None:
                    backup_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                    backup = Path(tempfile.mkdtemp(prefix=stamp + "-links-", dir=backup_root))
                saved = backup / target.relative_to(home)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved, follow_symlinks=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(".dotfiles-link-" + uuid.uuid4().hex)
            try:
                temporary.symlink_to(source)
                os.replace(temporary, target)
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
                    shutil.copy2(saved, target, follow_symlinks=False)
        raise
    print(f"Ссылок создано: {len(completed)}. Backup: {backup or 'не понадобился'}")
    return backup


def adopt_main(restored, home=None):
    home = normal_home(home)
    restored = Path(restored)
    target = home / "Main"
    if os.path.lexists(target):
        raise LinkError("Main уже существует: восстановленная копия оставлена отдельно, без замены данных.")
    if not restored.is_relative_to(home) or restored.is_symlink() or not restored.is_dir():
        raise LinkError("Неверная папка восстановленного Main.")
    plan(home, main_root=restored)
    report = restored.parent
    restored.chmod(0o700)
    os.rename(restored, target)
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
    entries = plan(sources=mode not in {"--destinations-only", "--zsh-config"})
    if mode == "--apply":
        apply()
    elif mode == "--check":
        wrong = [target for source, target in entries if not correct_link(source, target)]
        if wrong:
            raise LinkError("Неверные или отсутствующие ссылки: " + ", ".join(str(target) for target in wrong))
        print(f"LINK CHECK PASSED: {len(entries)} ссылок на конфиги в Main.")
    elif mode == "--zsh-config":
        print(entries[0][0])
    elif mode == "--dry-run":
        for source, target in entries:
            print(("Unchanged link: " if correct_link(source, target) else "Link (backup if present): ") + f"{target} -> {source}")


if __name__ == "__main__":
    try:
        main()
    except (LinkError, OSError) as error:
        print("Ошибка ссылок: " + str(error), file=sys.stderr)
        sys.exit(1)
