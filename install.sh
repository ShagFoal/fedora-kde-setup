#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
(( $# <= 1 )) || { printf 'Only one option is supported.\n' >&2; exit 2; }
MODE=install
case "${1:-}" in
  '') ;;
  --dry-run) MODE=dry-run ;;
  --check) MODE=check ;;
  --restore) MODE=restore ;;
  --links-only) MODE=links-only ;;
  -h|--help)
    printf 'Usage: ./install.sh [--dry-run | --check | --restore | --links-only]\n'
    printf 'With --restore, recover Main from the configured rclone remote. Run ./install.sh afterwards to apply settings.\n'
    printf 'Run as your regular user. sudo is used only for the system package manager.\n'
    exit 0 ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
TEMP_DIR=
BACKUP_DIR=
CHANGED=0
cleanup() { [[ -z "$TEMP_DIR" ]] || rm -rf -- "$TEMP_DIR"; }
trap cleanup EXIT
trap 'printf "ERROR: line %s. Installation stopped; backups: %s\n" "$LINENO" "${BACKUP_DIR:-none needed yet}" >&2' ERR
trap 'exit 130' INT
trap 'exit 143' TERM

[[ $EUID -ne 0 ]] || die 'Run without sudo; the script requests sudo only for the system package manager.'
if [[ "$MODE" = restore && ( ! -t 0 || ! -t 1 ) ]]; then
  die '--restore requires an interactive terminal for credentials and snapshot selection.'
fi
[[ -n ${HOME:-} && $HOME = /* && $HOME != / ]] || die 'HOME must be an absolute user directory.'
[[ -d "$HOME" ]] || die 'HOME does not exist.'
[[ "$(realpath -ms -- "$HOME")" = "$HOME" ]] || die 'HOME must be a normalized absolute path.'
[[ -r /etc/os-release ]] || die 'Cannot identify the operating system.'
# This is the root-owned OS identification file, never a repository config.
source /etc/os-release
[[ ${ID:-} = fedora && ${VERSION_ID:-} = 45 ]] || die 'This installer targets Fedora 45.'
[[ ! -e /run/ostree-booted ]] || die 'This installer requires an RPM-based Fedora 45 installation with DNF5.'

# Verify the checkout before running any of its Python helpers.
[[ -f "$REPO_DIR/SHA256SUMS" && ! -L "$REPO_DIR/SHA256SUMS" ]] || die 'Missing regular SHA256SUMS.'
(cd -- "$REPO_DIR" && sha256sum --check --status SHA256SUMS) || die 'Repository integrity check failed; review edits and regenerate SHA256SUMS.'

if [[ "$MODE" = restore ]]; then
  [[ ! -e "$HOME/Main" && ! -L "$HOME/Main" ]] || die 'Main already exists. Run ./install.sh to apply its settings.'
  for command in python3 restic rclone; do
    command -v "$command" >/dev/null || die "Install $command before restoring Main. See README.md."
  done
  exec python3 -B "$REPO_DIR/scripts/restore.py" "$REPO_DIR/restore.json" --configured --activate-main
elif [[ "$MODE" = links-only ]]; then
  command -v python3 >/dev/null || die 'Python 3 is required to link Main.'
  exec python3 -B "$REPO_DIR/scripts/links.py" --apply
fi

ARCH=$(uname -m)
case "$ARCH" in x86_64|aarch64) ;; *) die "Unsupported architecture: $ARCH" ;; esac

CONFIG_HOME=${XDG_CONFIG_HOME:-"$HOME/.config"}
DATA_HOME=${XDG_DATA_HOME:-"$HOME/.local/share"}
STATE_HOME=${XDG_STATE_HOME:-"$HOME/.local/state"}
ZSH_HOME=${ZDOTDIR:-"$HOME"}
for base in "$CONFIG_HOME" "$DATA_HOME" "$STATE_HOME" "$ZSH_HOME"; do
  [[ "$base" = "$HOME" || "$base" = "$HOME/"* ]] || die 'XDG and ZDOTDIR paths must stay inside HOME.'
  [[ "$(realpath -ms -- "$base")" = "$base" ]] || die 'XDG and ZDOTDIR paths must be normalized.'
done
[[ ${STARSHIP_CONFIG:-"$CONFIG_HOME/starship.toml"} = "$CONFIG_HOME/starship.toml" ]] || die 'STARSHIP_CONFIG overrides the managed config.'

resolve_target() {
  case "$1" in
    .zshrc) printf '%s/.zshrc' "$ZSH_HOME" ;;
    .config/*) printf '%s/%s' "$CONFIG_HOME" "${1#.config/}" ;;
    .local/share/*) printf '%s/%s' "$DATA_HOME" "${1#.local/share/}" ;;
    *) printf '%s/%s' "$HOME" "$1" ;;
  esac
}

safe_file() {
  local target=$1 parent
  [[ "$target" = "$HOME/"* ]] || die "Target is outside HOME: $target"
  [[ "$(realpath -ms -- "$target")" = "$target" ]] || die "Unsafe target: $target"
  [[ ! -L "$target" ]] || die "Refusing a symbolic link: $target"
  [[ ! -e "$target" || -f "$target" ]] || die "Expected a regular file: $target"
  parent=$(dirname -- "$target")
  while [[ "$parent" != / ]]; do
    [[ ! -L "$parent" ]] || die "Refusing a symbolic-link directory: $parent"
    [[ ! -e "$parent" || -d "$parent" ]] || die "Expected a directory: $parent"
    parent=$(dirname -- "$parent")
  done
}

package_installed() {
  local capability=$1
  # Fedora ships both full curl and a minimal build with HTTPS support.
  [[ "$capability" != curl ]] || capability=/usr/bin/curl
  rpm -q --quiet --whatprovides "$capability"
}

command -v rpm >/dev/null || die 'RPM is required to check installed packages.'
readonly -a PACKAGES=(
  zsh konsole fastfetch dolphin git curl python3 fontconfig util-linux restic rclone
  ca-certificates diffutils gh openssh-clients xdg-utils
)
declare -a MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  package_installed "$package" || MISSING_PACKAGES+=("$package")
done

[[ -f "$REPO_DIR/dependencies.tsv" && ! -L "$REPO_DIR/dependencies.tsv" ]] || die 'Missing regular dependency lock.'
if command -v python3 >/dev/null; then
  if [[ "$MODE" = install ]]; then
    python3 -B "$REPO_DIR/scripts/links.py" --validate
  fi
elif [[ "$MODE" = dry-run || "$MODE" = check ]]; then
  die 'Python 3 is required for config-link validation.'
fi
safe_file "$STATE_HOME/dotfiles/install.lock"
safe_file "$STATE_HOME/dotfiles/backups/.preflight"
while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
  [[ -n "$arch" && "$arch" != \#* ]] || continue
  [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
  [[ "$archive_hash" =~ ^[0-9a-f]{64}$ && "$file_hash" =~ ^[0-9a-f]{64}$ ]] || die 'Invalid dependency hash.'
  [[ "$url" = https://github.com/* || "$url" = https://raw.githubusercontent.com/* ]] || die 'Expected an official HTTPS GitHub dependency URL.'
  [[ "$mode" = 644 || "$mode" = 755 ]] || die 'Invalid dependency mode.'
  safe_file "$(resolve_target "$relative")"
done < "$REPO_DIR/dependencies.tsv"

matches_hash() {
  [[ -f "$1" && ! -L "$1" ]] || return 1
  local actual
  actual=$(sha256sum -- "$1")
  [[ "${actual%% *}" = "$2" ]]
}

if [[ "$MODE" = dry-run ]]; then
  note "DRY RUN: Fedora $VERSION_ID / $ARCH"
  if (( ${#MISSING_PACKAGES[@]} )); then
    note "Would run: sudo dnf5 install -y ${MISSING_PACKAGES[*]}"
  else
    note 'All required RPM packages are installed.'
  fi
  python3 -B "$REPO_DIR/scripts/links.py" --dry-run
  while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
    [[ -n "$arch" && "$arch" != \#* ]] || continue
    [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
    target=$(resolve_target "$relative")
    if matches_hash "$target" "$file_hash" && [[ "$mode" != 755 || -x "$target" ]]; then
      note "Dependency unchanged: $target"
    else
      note "Download, verify, copy (backup if present): $target"
    fi
  done < "$REPO_DIR/dependencies.tsv"
  exit 0
fi

check_installation() {
  local failed=0 relative target arch url archive_hash member file_hash mode
  if (( ${#MISSING_PACKAGES[@]} )); then
    note "Missing RPM packages: ${MISSING_PACKAGES[*]}"
    failed=1
  fi
  python3 -B "$REPO_DIR/scripts/links.py" --check || failed=1
  while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
    [[ -n "$arch" && "$arch" != \#* ]] || continue
    [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
    target=$(resolve_target "$relative")
    if ! matches_hash "$target" "$file_hash" || { [[ "$mode" = 755 ]] && [[ ! -x "$target" ]]; }; then
      note "Dependency differs or is missing: $target"
      failed=1
    fi
  done < "$REPO_DIR/dependencies.tsv"
  if command -v zsh >/dev/null; then
    zsh -dfn "$(python3 -B "$REPO_DIR/scripts/links.py" --zsh-config)" || failed=1
  else
    failed=1
  fi
  (( failed == 0 )) || return 1
  note "CHECK PASSED: Fedora packages, Main links, pinned dependencies and Zsh syntax."
}

if [[ "$MODE" = check ]]; then
  check_installation || exit 1
  exit 0
fi

mkdir -p -- "$STATE_HOME/dotfiles"
exec 9>> "$STATE_HOME/dotfiles/install.lock"
flock -n 9 || die 'Another dotfiles installation is running.'
TEMP_DIR=$(mktemp -d)
note "[1/4] Installing missing Fedora RPM packages."
if (( ${#MISSING_PACKAGES[@]} )); then
  command -v sudo >/dev/null || die 'sudo is required to install missing packages.'
  command -v dnf5 >/dev/null || die 'DNF5 is required to install missing packages.'
  sudo dnf5 install -y "${MISSING_PACKAGES[@]}"
fi
MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  package_installed "$package" || die "Package was not installed: $package"
done
python3 -B "$REPO_DIR/scripts/links.py" --validate
zsh -dfn "$(python3 -B "$REPO_DIR/scripts/links.py" --zsh-config)"

write_copy() {
  local source=$1 target=$2 mode=$3 temporary backup
  safe_file "$target"
  if cmp -s -- "$source" "$target" && { [[ "$mode" != 755 ]] || [[ -x "$target" ]]; }; then
    return 0
  fi
  if [[ -e "$target" ]]; then
    if [[ -z "$BACKUP_DIR" ]]; then
      mkdir -p -- "$STATE_HOME/dotfiles/backups"
      BACKUP_DIR=$(mktemp -d "$STATE_HOME/dotfiles/backups/$(date -u +%Y%m%dT%H%M%SZ).XXXXXX")
    fi
    backup="$BACKUP_DIR/${target#"$HOME/"}"
    mkdir -p -- "$(dirname -- "$backup")"
    cp --preserve=mode,timestamps --no-dereference -- "$target" "$backup"
  fi
  mkdir -p -- "$(dirname -- "$target")"
  temporary=$(mktemp "$(dirname -- "$target")/.dotfiles.XXXXXX")
  if ! install -m "$mode" -- "$source" "$temporary" || ! mv -fT -- "$temporary" "$target"; then
    rm -f -- "$temporary"
    die "Cannot copy $target; backups: ${BACKUP_DIR:-none needed yet}"
  fi
  CHANGED=$((CHANGED + 1))
  note "Copied: $target"
}

note '[2/4] Preparing pinned dependencies; every download is checked before use.'
while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
  [[ -n "$arch" && "$arch" != \#* ]] || continue
  [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
  target=$(resolve_target "$relative")
  if matches_hash "$target" "$file_hash" && { [[ "$mode" != 755 ]] || [[ -x "$target" ]]; }; then
    continue
  fi
  archive="$TEMP_DIR/$archive_hash"
  if [[ ! -f "$archive" ]]; then
    curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' --tlsv1.2 \
      --connect-timeout 15 --max-time 300 --retry 2 --output "$archive" "$url"
    matches_hash "$archive" "$archive_hash" || die 'Downloaded dependency checksum mismatch.'
  fi
  prepared="$TEMP_DIR/$file_hash.file"
  if [[ "$member" = - ]]; then
    cp -- "$archive" "$prepared"
  else
    python3 - "$archive" "$member" "$prepared" <<'PY'
import pathlib
import sys
import tarfile

with tarfile.open(sys.argv[1]) as archive:
    member = archive.getmember(sys.argv[2])
    if not member.isfile() or member.size > 100 * 1024 * 1024:
        raise SystemExit('Expected a small regular archive member')
    # Read one exact member, never extract archive paths or links.
    pathlib.Path(sys.argv[3]).write_bytes(archive.extractfile(member).read())
PY
  fi
  matches_hash "$prepared" "$file_hash" || die 'Extracted dependency checksum mismatch.'
done < "$REPO_DIR/dependencies.tsv"

note '[3/4] Copying dependencies and linking Main configs; changed files get backups.'
while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
  [[ -n "$arch" && "$arch" != \#* ]] || continue
  [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
  target=$(resolve_target "$relative")
  if matches_hash "$target" "$file_hash" && { [[ "$mode" != 755 ]] || [[ -x "$target" ]]; }; then
    continue
  fi
  write_copy "$TEMP_DIR/$file_hash.file" "$target" "$mode"
done < "$REPO_DIR/dependencies.tsv"
python3 -B "$REPO_DIR/scripts/links.py" --apply
if (( CHANGED > 0 )); then
  fc-cache "$DATA_HOME/fonts/JetBrainsMonoNerdFont"
fi
note '[4/4] Checking the result.'
check_installation
note "Complete. Files changed: $CHANGED. Backups: ${BACKUP_DIR:-none needed}."
note 'Reopen Konsole and Dolphin to load the settings in Main.'
