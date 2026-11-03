#!/usr/bin/env bash
# Safe local installer. Never installs into the system Python.
# Usage: bash install_deps.sh

set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$ROOT/scripts/install_local.sh" "$@"
