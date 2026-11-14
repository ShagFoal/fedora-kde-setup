#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

[[ -n ${REPO_DIR:-} && -n ${SETUP_PLATFORM:-} && -n ${SETUP_ENTRYPOINT:-} ]] || {
  printf 'Run a platform install*.sh entrypoint from the repository root.\n' >&2
  exit 2
}
MODE=install
case "${1:-}" in
  '') ;;
  --dry-run) MODE=dry-run ;;
  --check) MODE=check ;;
  --restore) MODE=restore ;;
  --links-only) MODE=links-only ;;
  -h|--help)
    printf 'Usage: ./%s [--dry-run | --check | --restore | --links-only]\n' "$SETUP_ENTRYPOINT"
    printf 'Run as your regular user. sudo is used only for the system package manager.\n'
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
case "$SETUP_PLATFORM" in
  fedora)
    [[ ${ID:-} = fedora && ${VERSION_ID:-} = 45 ]] || die 'This installer targets Fedora 45.'
    readonly PLATFORM_NAME='Fedora 45' PACKAGE_KIND=RPM
    command -v rpm >/dev/null || die 'RPM is required to check installed packages.'
    ;;
  kubuntu)
    [[ ( ${ID:-} = ubuntu || ${ID:-} = kubuntu ) && ${VERSION_ID:-} = 26.10 ]] || die 'This installer targets Kubuntu 26.10.'
    readonly PLATFORM_NAME='Kubuntu 26.10' PACKAGE_KIND=DEB
    command -v dpkg-query >/dev/null || die 'dpkg-query is required to check installed packages.'
    ;;
  tumbleweed)
    [[ ${ID:-} = opensuse-tumbleweed ]] || die 'This installer targets openSUSE Tumbleweed.'
    readonly PLATFORM_NAME='openSUSE Tumbleweed' PACKAGE_KIND=RPM
    command -v rpm >/dev/null || die 'RPM is required to check installed packages.'
    ;;
  *) die 'Unsupported installer platform.' ;;
esac
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
  if [[ "$SETUP_PLATFORM" = fedora ]]; then
    rpm -q --quiet "$1"
  elif [[ "$SETUP_PLATFORM" = tumbleweed ]]; then
    # Tumbleweed can provide unversioned Python through a versioned RPM.
    rpm -q --quiet --whatprovides "$1"
  else
    local status
    status=$(LC_ALL=C dpkg-query -W -f='${Status}' "$1" 2>/dev/null) || return 1
    [[ "$status" = 'install ok installed' || "$status" = 'hold ok installed' ]]
  fi
}

if [[ "$SETUP_PLATFORM" = kubuntu ]]; then
  package_installed kubuntu-settings-desktop || die 'Kubuntu desktop settings are missing. Install Kubuntu before running this setup.'
elif [[ "$SETUP_PLATFORM" = tumbleweed ]]; then
  package_installed plasma6-session || die 'Plasma 6 is missing. Install the KDE desktop before running this setup.'
fi

PACKAGES=(zsh konsole fastfetch dolphin git curl python3 fontconfig util-linux restic rclone)
if [[ "$SETUP_PLATFORM" = kubuntu ]]; then
  # Minimal installations may omit Git's SSH transport and desktop URL helpers.
  # These are explicit because APT Recommends are disabled for this profile.
  PACKAGES+=(ca-certificates diffutils gh openssh-client xdg-utils)
elif [[ "$SETUP_PLATFORM" = tumbleweed ]]; then
  PACKAGES=(zsh konsole fastfetch dolphin git-core curl python3 fontconfig util-linux restic rclone
    ca-certificates ca-certificates-mozilla diffutils gh openssh-clients xdg-utils)
fi
readonly -a PACKAGES
declare -a MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  package_installed "$package" || MISSING_PACKAGES+=("$package")
done

[[ -f "$REPO_DIR/SHA256SUMS" && ! -L "$REPO_DIR/SHA256SUMS" ]] || die 'Missing regular SHA256SUMS.'
(cd -- "$REPO_DIR" && sha256sum --check --status SHA256SUMS) || die 'Repository integrity check failed; review edits and regenerate SHA256SUMS.'
[[ -f "$REPO_DIR/dependencies.tsv" && ! -L "$REPO_DIR/dependencies.tsv" ]] || die 'Missing regular dependency lock.'
if [[ "$MODE" = restore && ( -e "$HOME/Main" || -L "$HOME/Main" ) ]]; then
  die 'Main already exists. Use the normal install to link its configs; --restore never replaces Main.'
fi
if command -v python3 >/dev/null; then
  if [[ "$MODE" = restore ]]; then
    python3 "$REPO_DIR/scripts/links.py" --destinations-only
  else
    python3 "$REPO_DIR/scripts/links.py" --validate
  fi
elif [[ "$MODE" = dry-run || "$MODE" = check || "$MODE" = links-only ]]; then
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

warnings() {
  note 'Optional: rebootw requires efibootmgr, UEFI and a verified Windows Boot0000 entry; it is never called by this installer.'
  note 'Excluded: bm/backup-main, backup schedules, JDK/.NET/Rust SDKs, Git identity/credentials and other KDE settings.'
  note 'Restic/rclone are installed; Main files are restored only with --restore and interactive credentials.'
  note 'The Konsole profile starts /bin/zsh; your account login shell is not changed.'
  note 'Dolphin: behavior and interface settings are included; color schemes and themes are not copied.'
  note 'Close Dolphin before installing its settings.'
  note 'MPV: only mpv.conf is restored; install the player yourself.'
  note 'Plasma keyboard/shortcuts/desktops are configured manually; see PLASMA_MANUAL.md.'
  if [[ "$SETUP_PLATFORM" = kubuntu ]]; then
    note 'Kubuntu Minimal profile: only explicit packages and required dependencies; APT Recommends are disabled.'
    note 'Kubuntu preparation, drivers and optional apps: see KUBUNTU.md.'
  elif [[ "$SETUP_PLATFORM" = tumbleweed ]]; then
    note 'Tumbleweed: required packages only (--no-recommends); existing package vendors are preserved.'
    note 'Update Tumbleweed separately with zypper dup; Packman, drivers and optional apps: see TUMBLEWEED.md.'
  fi
  note 'Live configs stay in Main; keep their source folder and back it up with Main.'
}

if [[ "$MODE" = dry-run ]]; then
  note 'DRY RUN: no downloads, sudo, copies, backups or settings changes.'
  note "Target: $PLATFORM_NAME / $ARCH; missing $PACKAGE_KIND packages: ${MISSING_PACKAGES[*]:-none}"
  if [[ "$SETUP_PLATFORM" = kubuntu && ${#MISSING_PACKAGES[@]} -gt 0 ]]; then
    note 'Would run: sudo apt-get update; then sudo apt-get install -y --no-remove --no-install-recommends with the missing packages.'
  elif [[ "$SETUP_PLATFORM" = tumbleweed && ${#MISSING_PACKAGES[@]} -gt 0 ]]; then
    note 'Would run: sudo zypper --non-interactive refresh; then sudo zypper --non-interactive install --no-recommends --no-allow-vendor-change with the missing packages.'
  fi
  python3 "$REPO_DIR/scripts/links.py" --dry-run
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
    note "Missing $PACKAGE_KIND packages: ${MISSING_PACKAGES[*]}"
    failed=1
  fi
  python3 "$REPO_DIR/scripts/links.py" --check || failed=1
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
    zsh -dfn "$(python3 "$REPO_DIR/scripts/links.py" --zsh-config)" || failed=1
  else
    failed=1
  fi
  (( failed == 0 )) || return 1
  note "CHECK PASSED: 9 Main config links, pinned dependencies and Zsh syntax."
}

if [[ "$MODE" = check ]]; then
  check_installation
  warnings
  exit 0
fi

if [[ "$MODE" = links-only ]]; then
  python3 "$REPO_DIR/scripts/links.py" --apply
  exit 0
fi

mkdir -p -- "$STATE_HOME/dotfiles"
exec 9>> "$STATE_HOME/dotfiles/install.lock"
flock -n 9 || die 'Another dotfiles installation is running.'
TEMP_DIR=$(mktemp -d)
note "[1/4] Installing missing $PACKAGE_KIND packages."
if (( ${#MISSING_PACKAGES[@]} )); then
  command -v sudo >/dev/null || die 'sudo is required to install missing packages.'
  if [[ "$SETUP_PLATFORM" = fedora ]]; then
    sudo dnf install -y "${MISSING_PACKAGES[@]}"
  elif [[ "$SETUP_PLATFORM" = kubuntu ]]; then
    command -v apt-get >/dev/null || die 'APT is required to install missing packages.'
    sudo apt-get -o APT::Update::Error-Mode=any update
    sudo apt-get install -y --no-remove --no-install-recommends "${MISSING_PACKAGES[@]}"
  else
    command -v zypper >/dev/null || die 'Zypper is required to install missing packages.'
    sudo zypper --non-interactive refresh
    sudo zypper --non-interactive install --no-recommends --no-allow-vendor-change "${MISSING_PACKAGES[@]}"
  fi
fi
MISSING_PACKAGES=()
for package in "${PACKAGES[@]}"; do
  package_installed "$package" || die "Package was not installed: $package"
done
if [[ "$MODE" = restore ]]; then
  python3 "$REPO_DIR/scripts/restore.py" "$REPO_DIR/restore.json" --activate-main
fi
python3 "$REPO_DIR/scripts/links.py" --validate
zsh -dfn "$(python3 "$REPO_DIR/scripts/links.py" --zsh-config)"

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
python3 "$REPO_DIR/scripts/links.py" --apply
if (( CHANGED > 0 )); then
  fc-cache "$DATA_HOME/fonts/JetBrainsMonoNerdFont"
fi
note '[4/4] Checking the result.'
check_installation
note "Complete. Files changed: $CHANGED. Backups: ${BACKUP_DIR:-none needed}."
warnings
note 'Close and reopen Konsole and Dolphin after the installer exits. Keep the configs in Main; the temporary bootstrap checkout may be deleted.'
