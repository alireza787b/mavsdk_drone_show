#!/bin/bash

# Global variables
VERSION="v2.12.12"
ARM64_URL="https://github.com/mavlink/MAVSDK/releases/download/$VERSION/mavsdk_server_linux-arm64-musl"
X86_64_URL="https://github.com/mavlink/MAVSDK/releases/download/$VERSION/mavsdk_server_musl_x86_64"
DOWNLOAD_DIR="/opt/mavsdk_server"
FILENAME="mavsdk_server"

# Function: download_mavsdk
# Downloads MAVSDK binary based on architecture or SITL mode flag
download_mavsdk() {
    local url
    if [[ $1 == "--sitl" ]]; then
        printf "SITL mode detected, downloading x86_64 binary...\n"
        url="$X86_64_URL"
    else
        printf "Non-SITL mode, downloading ARM64 binary...\n"
        url="$ARM64_URL"
    fi

    # Create download directory if it doesn't exist
    mkdir -p "$DOWNLOAD_DIR"

    # Download the binary
    if ! curl -L "$url" -o "$DOWNLOAD_DIR/$FILENAME"; then
        printf "Error: Failed to download MAVSDK binary from %s\n" "$url" >&2
        return 1
    fi

    # Make the file executable
    if ! chmod +x "$DOWNLOAD_DIR/$FILENAME"; then
        printf "Error: Failed to make the binary executable\n" >&2
        return 1
    fi

    printf "Download complete: %s\n" "$DOWNLOAD_DIR/$FILENAME"
}

# Main function: checks for SITL flag and initiates download
main() {
    if [[ $1 == "--sitl" ]]; then
        download_mavsdk "--sitl" || exit 1
    else
        download_mavsdk || exit 1
    fi
}

# Execute main function with all script arguments
main "$@"
