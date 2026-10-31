#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
MODE=install
case "${1:-}" in
  '') ;;
  --dry-run) MODE=dry-run ;;
  --check) MODE=check ;;
  -h|--help)
    printf 'Usage: ./install.sh [--dry-run | --check]\n'
    printf 'Run as your regular user. sudo is used only to install missing RPM packages.\n'
    exit 0 ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac
(( $# <= 1 )) || { printf 'Only one option is supported.\n' >&2; exit 2; }

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

[[ $EUID -ne 0 ]] || die 'Run without sudo; the script requests sudo only for DNF.'
[[ -n ${HOME:-} && $HOME = /* && $HOME != / ]] || die 'HOME must be an absolute user directory.'
[[ -d "$HOME" ]] || die 'HOME does not exist.'
[[ "$(realpath -ms -- "$HOME")" = "$HOME" ]] || die 'HOME must be a normalized absolute path.'
[[ -r /etc/os-release ]] || die 'Cannot identify the operating system.'
# This is the root-owned OS identification file, never a repository config.
source /etc/os-release
[[ ${ID:-} = fedora && ${VERSION_ID:-} = 45 ]] || die 'This installer targets Fedora 45.'
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

readonly -a CONFIGS=(
  '.zshrc'
  '.config/starship.toml'
  '.config/konsolerc'
  '.local/share/konsole/Profile 1.profile'
  '.local/share/konsole/Catppuccin-Mocha.colorscheme'
  '.config/fastfetch/config.jsonc'
  '.config/dolphinrc'
  '.local/share/kxmlgui5/dolphin/dolphinui.rc'
  '.config/mpv/mpv.conf'
  '.config/kxkbrc'
)
readonly -a MERGED_CONFIGS=(
  '.config/kcminputrc'
  '.config/kglobalshortcutsrc'
  '.config/kwinrc'
)
readonly CONFIG_COUNT=$(( ${#CONFIGS[@]} + ${#MERGED_CONFIGS[@]} ))
readonly -a PACKAGES=(zsh konsole fastfetch dolphin git curl python3 fontconfig util-linux)
declare -a MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  rpm -q --quiet "$package" || MISSING_PACKAGES+=("$package")
done

[[ -f "$REPO_DIR/SHA256SUMS" && ! -L "$REPO_DIR/SHA256SUMS" ]] || die 'Missing regular SHA256SUMS.'
(cd -- "$REPO_DIR" && sha256sum --check --status SHA256SUMS) || die 'Repository integrity check failed; review edits and regenerate SHA256SUMS.'
[[ -f "$REPO_DIR/dependencies.tsv" && ! -L "$REPO_DIR/dependencies.tsv" ]] || die 'Missing regular dependency lock.'
for relative in "${CONFIGS[@]}" "${MERGED_CONFIGS[@]}"; do
  [[ -f "$REPO_DIR/files/$relative" && ! -L "$REPO_DIR/files/$relative" ]] || die "Missing regular config: $relative"
  source_parent=$(dirname -- "$REPO_DIR/files/$relative")
  while [[ "$source_parent" != "$REPO_DIR" ]]; do
    [[ ! -L "$source_parent" ]] || die "Symbolic link in source path: $source_parent"
    source_parent=$(dirname -- "$source_parent")
  done
  safe_file "$(resolve_target "$relative")"
done
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

warnings() {
  note 'Optional: rebootw requires efibootmgr, UEFI and a verified Windows Boot0000 entry; it is never called by this installer.'
  note 'Excluded: bm/backup-main, Restic/Rclone backups, JDK/.NET/Rust SDKs, Git identity/credentials and other KDE settings.'
  note 'The Konsole profile starts /bin/zsh; your account login shell is not changed.'
  note 'Dolphin: behavior and interface settings are included; color schemes and themes are not copied.'
  note 'Close Dolphin before installing its settings.'
  note 'MPV: only mpv.conf is restored; install the player yourself.'
  note 'Keyboard, selected KDE shortcuts and the desktop grid take effect after logging out of Plasma and back in.'
}

if [[ "$MODE" = dry-run ]]; then
  note 'DRY RUN: no downloads, sudo, copies, backups or settings changes.'
  note "Target: Fedora 45 / $ARCH; missing RPM packages: ${MISSING_PACKAGES[*]:-none}"
  for relative in "${CONFIGS[@]}"; do
    target=$(resolve_target "$relative")
    if cmp -s -- "$REPO_DIR/files/$relative" "$target"; then
      note "Unchanged: $target"
    else
      note "Copy (backup if present): $target"
    fi
  done
  for relative in "${MERGED_CONFIGS[@]}"; do
    target=$(resolve_target "$relative")
    if command -v python3 >/dev/null && python3 "$REPO_DIR/scripts/merge-kconfig.py" --check "$REPO_DIR/files/$relative" "$target"; then
      note "Selected entries unchanged: $target"
    else
      note "Merge selected entries (backup if changed): $target"
    fi
  done
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
  warnings
  exit 0
fi

check_installation() {
  local failed=0 relative target arch url archive_hash member file_hash mode
  if (( ${#MISSING_PACKAGES[@]} )); then
    note "Missing RPM packages: ${MISSING_PACKAGES[*]}"
    failed=1
  fi
  for relative in "${CONFIGS[@]}"; do
    target=$(resolve_target "$relative")
    cmp -s -- "$REPO_DIR/files/$relative" "$target" || { note "Config differs or is missing: $target"; failed=1; }
  done
  for relative in "${MERGED_CONFIGS[@]}"; do
    target=$(resolve_target "$relative")
    if ! command -v python3 >/dev/null || ! python3 "$REPO_DIR/scripts/merge-kconfig.py" --check "$REPO_DIR/files/$relative" "$target"; then
      note "Selected config entries differ or are missing: $target"
      failed=1
    fi
  done
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
    zsh -dfn "$REPO_DIR/files/.zshrc" || failed=1
  else
    failed=1
  fi
  (( failed == 0 )) || return 1
  note "CHECK PASSED: $CONFIG_COUNT config files/fragments, pinned dependencies and Zsh syntax."
}

if [[ "$MODE" = check ]]; then
  check_installation
  warnings
  exit 0
fi

mkdir -p -- "$STATE_HOME/dotfiles"
exec 9>> "$STATE_HOME/dotfiles/install.lock"
flock -n 9 || die 'Another dotfiles installation is running.'
TEMP_DIR=$(mktemp -d)
note '[1/4] Installing missing RPM packages.'
if (( ${#MISSING_PACKAGES[@]} )); then
  command -v sudo >/dev/null || die 'sudo is required to install missing packages.'
  sudo dnf install -y "${MISSING_PACKAGES[@]}"
fi
MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  rpm -q --quiet "$package" || die "Package was not installed: $package"
done
zsh -dfn "$REPO_DIR/files/.zshrc"

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

note "[3/4] Copying dependencies and applying $CONFIG_COUNT config files/fragments; changed files get backups."
while IFS=$'\t' read -r arch url archive_hash member file_hash relative mode; do
  [[ -n "$arch" && "$arch" != \#* ]] || continue
  [[ "$arch" = all || "$arch" = "$ARCH" ]] || continue
  target=$(resolve_target "$relative")
  if matches_hash "$target" "$file_hash" && { [[ "$mode" != 755 ]] || [[ -x "$target" ]]; }; then
    continue
  fi
  write_copy "$TEMP_DIR/$file_hash.file" "$target" "$mode"
done < "$REPO_DIR/dependencies.tsv"
for relative in "${CONFIGS[@]}"; do
  write_copy "$REPO_DIR/files/$relative" "$(resolve_target "$relative")" 644
done
for relative in "${MERGED_CONFIGS[@]}"; do
  target=$(resolve_target "$relative")
  python3 "$REPO_DIR/scripts/merge-kconfig.py" --render "$REPO_DIR/files/$relative" "$target" "$TEMP_DIR/merged-config"
  write_copy "$TEMP_DIR/merged-config" "$target" 644
done
if (( CHANGED > 0 )); then
  fc-cache "$DATA_HOME/fonts/JetBrainsMonoNerdFont"
fi
note '[4/4] Checking the result.'
check_installation
note "Complete. Files changed: $CHANGED. Backups: ${BACKUP_DIR:-none needed}."
warnings
note 'Close and reopen Konsole and Dolphin after the installer exits. The repository can then be deleted.'
