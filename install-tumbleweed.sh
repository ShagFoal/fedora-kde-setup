#!/usr/bin/env bash
set -Eeuo pipefail

readonly REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly SETUP_PLATFORM=tumbleweed
readonly SETUP_ENTRYPOINT=install-tumbleweed.sh

# Verify the shared implementation before sourcing any repository code.
[[ -f "$REPO_DIR/SHA256SUMS" && ! -L "$REPO_DIR/SHA256SUMS" ]] || {
  printf 'ERROR: Missing regular SHA256SUMS.\n' >&2
  exit 1
}
(cd -- "$REPO_DIR" && sha256sum --check --status SHA256SUMS) || {
  printf 'ERROR: Repository integrity check failed; review edits and regenerate SHA256SUMS.\n' >&2
  exit 1
}
source "$REPO_DIR/scripts/install-common.sh"
