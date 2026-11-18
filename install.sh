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
    printf 'The default install fetches the latest upstream dependencies. --check verifies the local installation.\n'
    printf 'With --restore, recover Main from the configured rclone remote. Run ./install.sh afterwards to apply settings.\n'
    printf 'Run as your regular user. sudo is used only for the system package manager.\n'
    exit 0 ;;
  *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
esac

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '%s\n' "$*"; }
trap 'printf "ERROR: line %s. Installation stopped.\n" "$LINENO" >&2' ERR
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

if command -v python3 >/dev/null; then
  if [[ "$MODE" = install ]]; then
    python3 -B "$REPO_DIR/scripts/links.py" --validate
    python3 -B "$REPO_DIR/scripts/dependencies.py" validate "$ARCH"
  fi
elif [[ "$MODE" = dry-run || "$MODE" = check ]]; then
  die 'Python 3 is required for config-link validation.'
fi
safe_file "$STATE_HOME/dotfiles/install.lock"
safe_file "$STATE_HOME/dotfiles/backups/.preflight"

if [[ "$MODE" = dry-run ]]; then
  note "DRY RUN: Fedora $VERSION_ID / $ARCH"
  if (( ${#MISSING_PACKAGES[@]} )); then
    note "Would run: sudo dnf5 install -y ${MISSING_PACKAGES[*]}"
  else
    note 'All required RPM packages are installed.'
  fi
  python3 -B "$REPO_DIR/scripts/links.py" --dry-run
  python3 -B "$REPO_DIR/scripts/dependencies.py" plan "$ARCH"
  exit 0
fi

check_installation() {
  local failed=0 zsh_config
  if (( ${#MISSING_PACKAGES[@]} )); then
    note "Missing RPM packages: ${MISSING_PACKAGES[*]}"
    failed=1
  fi
  python3 -B "$REPO_DIR/scripts/links.py" --check || failed=1
  python3 -B "$REPO_DIR/scripts/dependencies.py" check "$ARCH" || failed=1
  if command -v zsh >/dev/null && zsh_config=$(python3 -B "$REPO_DIR/scripts/links.py" --zsh-config); then
    zsh -dfn "$zsh_config" || failed=1
  else
    failed=1
  fi
  (( failed == 0 )) || return 1
  note 'CHECK PASSED: Fedora packages, Main links, downloaded files and Zsh syntax.'
}

if [[ "$MODE" = check ]]; then
  check_installation || exit 1
  exit 0
fi

mkdir -p -- "$STATE_HOME/dotfiles"
exec 9>> "$STATE_HOME/dotfiles/install.lock"
flock -n 9 || die 'Another dotfiles installation is running.'
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
zsh_config=$(python3 -B "$REPO_DIR/scripts/links.py" --zsh-config)
zsh -dfn "$zsh_config"

note '[2/4] Fetching and verifying the latest upstream dependencies.'
python3 -B "$REPO_DIR/scripts/dependencies.py" install "$ARCH"
note '[3/4] Linking Main configs. Replaced files get backups.'
python3 -B "$REPO_DIR/scripts/links.py" --apply
note '[4/4] Checking the result.'
check_installation
note 'Complete.'
note 'Reopen Konsole and Dolphin to load the settings in Main.'
