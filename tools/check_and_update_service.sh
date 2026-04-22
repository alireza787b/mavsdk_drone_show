#!/bin/bash

# Backward-compatible wrapper around update_service.sh.
# Keeps the old entrypoint but uses the safe rendered-template installer.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${SCRIPT_DIR}/update_service.sh"
