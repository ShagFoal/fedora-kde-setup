#!/usr/bin/env bash
# One-time conversion of this user's Fedora fstab bind mount to a Main link.
set -Eeuo pipefail
umask 077
die() { printf '%s\n' "$*" >&2; exit 1; }

[[ $# = 0 || ( $# = 1 && $1 = --dry-run ) ]] || die 'Usage: migrate-projects-bind.sh [--dry-run]'
[[ $EUID != 0 ]] || die 'Запусти скрипт от своего пользователя в Konsole.'
scripts=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
fstab=/etc/fstab
backup="$fstab.before-projects-link-$UID"
source_dir="$HOME/Main/Projects"
target="$HOME/Projects"
[[ -d "$source_dir" && $(realpath -e -- "$source_dir") = "$source_dir" ]] || die "Проверь исходный каталог $source_dir."
[[ -f "$fstab" && ! -L "$fstab" ]] || die "Ожидался обычный файл $fstab."
exec 8< "$source_dir"
flock -n 8 || die 'Другой перенос Projects уже выполняется.'

# Print the line number of the exact Fedora bind entry. Decode fstab escapes
# before comparing paths and reject duplicate, foreign or unexpected options.
record() {
  python3 - "$1" "$source_dir" "$target" <<'PY'
import os, re, sys
path, source, target = sys.argv[1:]
def decode(field):
    return re.sub(r"\\(040|011|012|134)", lambda m: chr(int(m[1], 8)), field)
matches = []
with open(path, encoding="utf-8", errors="surrogateescape") as stream:
    for number, line in enumerate(stream, 1):
        fields = [decode(field) for field in line.split("#", 1)[0].split()]
        if len(fields) < 2 or os.path.normpath(fields[1]) != target:
            continue
        options = set(fields[3].split(",")) if len(fields) >= 4 else set()
        allowed = {"bind", "nofail", "defaults", "rw", "x-systemd.requires-mounts-for=" + source}
        if (fields[:3] != [source, target, "none"] or "bind" not in options
                or options - allowed or fields[4:] not in ([], ["0"], ["0", "0"])):
            sys.exit(f"В {path} другая запись для {target} (строка {number}).")
        matches.append(number)
if len(matches) > 1:
    sys.exit(f"В {path} несколько записей для {target}.")
if matches:
    print(matches[0])
PY
}

# findmnt --mountpoint may canonicalize a symlink. Compare the actual kernel
# mountpoint field, including hidden stacked mounts, before calling umount.
mount_count() {
  python3 - "$target" <<'PY'
import re, sys
target = sys.argv[1]
with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as info:
    print(sum(re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), line.split()[4]) == target for line in info))
PY
}

row=$(record "$fstab")
mounts=$(mount_count)
(( mounts <= 1 )) || die "Несколько монтирований на $target. Проверь findmnt."
if (( mounts )); then
  [[ -n "$row" && ! -L "$target" && "$source_dir" -ef "$target" ]] ||
    die "Точка монтирования $target не соответствует ожидаемой записи bind."
elif [[ -z "$row" && -L "$target" && $(realpath -e -- "$target") = "$source_dir" ]]; then
  printf 'Ссылка уже установлена: %s -> %s\n' "$target" "$source_dir"
  exit 0
fi
if [[ -e "$backup" || -L "$backup" ]]; then
  [[ -f "$backup" && ! -L "$backup" && -n $(record "$backup") ]] || die "Проверь существующую копию $backup."
  if [[ -n "$row" ]]; then
    cmp -s -- "$fstab" "$backup" || die "Существующая копия $backup отличается от $fstab."
  fi
elif [[ -z "$row" ]]; then
  die "В $fstab нет ожидаемой записи bind и не найдена копия предыдущего переноса."
fi
# Validate the rest of the plan before changing the active system mount.
python3 -B - "$scripts" "$target" "$mounts" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from links import LinkError, mount_conflict, mount_points, plan

target = Path(sys.argv[2])
mounts = mount_points()
if sys.argv[3] == "1":
    mounts.discard(target)
try:
    for source, dest in plan():
        conflict = mount_conflict(source, dest, mounts)
        if conflict:
            raise LinkError(conflict)
except (LinkError, OSError) as error:
    sys.exit(str(error))
PY

printf 'Перенос %s -> %s. Копия таблицы монтирования: %s\n' "$target" "$source_dir" "$backup"
if [[ ${1:-} = --dry-run ]]; then
  printf 'Активных монтирований: %s. Строка fstab: %s. Изменений нет.\n' "$mounts" "${row:-уже удалена}"
  exit 0
fi

if [[ -n "$row" ]]; then
  snapshot=$(mktemp)
  stage=
  cleanup() {
    rm -f -- "$snapshot"
    if [[ -n "$stage" ]]; then sudo rm -f -- "$stage"; fi
  }
  trap cleanup EXIT
  cp -- "$fstab" "$snapshot"
  [[ $(record "$snapshot") = "$row" ]] || die "$fstab изменился во время проверки."
  stage=$(sudo mktemp -- "${fstab%/*}/.fstab-projects.XXXXXXXX")
  sudo cp --preserve=all -- "$fstab" "$stage"
  sed "${row}d" "$snapshot" | sudo tee "$stage" >/dev/null
  cmp -s -- "$snapshot" "$fstab" || die "$fstab изменился. Запусти перенос ещё раз."
  [[ $(mount_count) = "$mounts" ]] || die "Точка монтирования $target изменилась."
  if (( mounts )); then
    [[ ! -L "$target" && "$source_dir" -ef "$target" ]] || die "Источник монтирования $target изменился."
    sudo umount -- "$target" || die "Не удалось отключить $target. Закрой использующие каталог программы. Запись fstab сохранена."
    [[ $(mount_count) = 0 ]] || die "$target всё ещё смонтирован."
  fi
  # A hard link retains the original inode and its metadata before atomic replacement.
  if [[ ! -e "$backup" ]]; then sudo ln -- "$fstab" "$backup"; fi
  cmp -s -- "$snapshot" "$fstab" && cmp -s -- "$snapshot" "$backup" || die "$fstab изменился. Проверь $backup."
  sudo mv -fT -- "$stage" "$fstab"
  stage=
fi
sudo systemctl daemon-reload
python3 -B "$scripts/links.py" --apply
python3 -B "$scripts/links.py" --check
