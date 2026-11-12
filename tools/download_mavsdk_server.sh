#!/bin/bash
# All server versions/assets/digests live in config/mavsdk-runtime.json.
# Default to the reviewed client/server pair, never a live "latest" lookup.
set -euo pipefail
MAVSDK_TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAVSDK_PROVISION_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --version|--url|--install-dir)
            [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 2; }
            MAVSDK_PROVISION_ARGS+=("$1" "$2"); shift 2 ;;
        --sitl)
            # Compatibility flag: architecture is detected, never forced.
            shift ;;
        --latest)
            echo "Automatic latest would split the reviewed Python/server pair. Update config/mavsdk-runtime.json and run the SDK migration gates." >&2
            exit 2 ;;
        --help|-h)
            echo "Usage: $0 [--version vX.Y.Z] [--url HTTPS_URL] [--install-dir DIR] [--sitl]"
            echo "Default: manifest-pinned server, verified SHA256/ELF/--help before atomic activation."
            echo "Overrides MDS_MAVSDK_VERSION/MDS_MAVSDK_URL are explicit custom compatibility choices."
            exit 0 ;;
        *) echo "Unknown option: $1" >&2; exit 2 ;;
    esac
done
exec python3 "$MAVSDK_TOOLS_DIR/mavsdk_runtime.py" install "${MAVSDK_PROVISION_ARGS[@]}"
