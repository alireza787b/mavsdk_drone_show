#!/bin/bash
# =============================================================================
# MDS Node Candidate Announce Helper
# =============================================================================
# Description: Re-send or preview a node identity announce to the GCS candidate registry
# =============================================================================

set -euo pipefail
IFS=$'\n\t'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/mds_init_lib"

source "${LIB_DIR}/common.sh"
source "${LIB_DIR}/announce.sh"

IDENTITY_FILE="${MDS_NODE_IDENTITY_FILE}"
LOCAL_ENV_FILE="${MDS_LOCAL_ENV}"
GCS_API_URL="${MDS_GCS_API_BASE_URL:-}"
REPORT_JSON=""
TIMEOUT_SEC="${DEFAULT_ANNOUNCE_TIMEOUT_SEC}"
DRY_RUN="false"

show_help() {
    cat << 'EOF'
MDS Node Candidate Announce Helper

USAGE:
    sudo ./tools/mds_node_announce.sh [OPTIONS]

DESCRIPTION:
    Read a node identity manifest and send the canonical candidate announce
    payload to the GCS enrollment registry.

OPTIONS:
    --gcs-api-url URL       Explicit GCS API base URL
                            Example: http://100.96.32.75:5000
    --identity-file PATH    Override node identity file
                            Default: /etc/mds/node_identity.json
    --local-env PATH        Override local.env path for URL discovery
                            Default: /etc/mds/local.env
    --timeout SEC           HTTP timeout in seconds (default: 15)
    --report-json PATH      Write machine-readable announce report
                            Use '-' to print JSON to stdout
    --dry-run               Build and print payload without sending it
    -h, --help              Show this help message

URL RESOLUTION ORDER:
    1. --gcs-api-url
    2. MDS_GCS_API_BASE_URL environment variable
    3. MDS_GCS_API_BASE_URL from local.env
    4. MDS_GCS_IP / GCS_IP with default port 5000

EXAMPLES:
    sudo ./tools/mds_node_announce.sh --gcs-api-url http://100.96.32.75:5000
    sudo ./tools/mds_node_announce.sh --dry-run --report-json -
    sudo ./tools/mds_node_announce.sh --local-env /etc/mds/local.env
EOF
}

parse_args() {
    local parsed
    parsed=$(getopt \
        -o h \
        --long help,gcs-api-url:,identity-file:,local-env:,timeout:,report-json:,dry-run \
        -n 'mds_node_announce.sh' -- "$@") || {
        echo "Error: invalid arguments. Use --help for usage." >&2
        exit 1
    }

    eval set -- "$parsed"

    while true; do
        case "$1" in
            --gcs-api-url)
                GCS_API_URL="$2"
                shift 2
                ;;
            --identity-file)
                IDENTITY_FILE="$2"
                shift 2
                ;;
            --local-env)
                LOCAL_ENV_FILE="$2"
                shift 2
                ;;
            --timeout)
                TIMEOUT_SEC="$2"
                shift 2
                ;;
            --report-json)
                REPORT_JSON="$2"
                shift 2
                ;;
            --dry-run)
                DRY_RUN="true"
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            --)
                shift
                break
                ;;
            *)
                echo "Error: unexpected argument $1" >&2
                exit 1
                ;;
        esac
    done
}

main() {
    parse_args "$@"
    init_logging

    if [[ ! -f "$IDENTITY_FILE" ]]; then
        log_error "Node identity manifest not found: $IDENTITY_FILE"
        exit 1
    fi

    local resolved_url
    resolved_url="$(resolve_gcs_api_base_url "$GCS_API_URL" "$LOCAL_ENV_FILE" 2>/dev/null || true)"
    if [[ -z "$resolved_url" ]]; then
        log_error "Unable to resolve GCS API URL. Provide --gcs-api-url or configure MDS_GCS_IP / MDS_GCS_API_BASE_URL."
        exit 1
    fi

    local report_path="$REPORT_JSON"
    if [[ "$report_path" == "-" ]]; then
        report_path="$(mktemp)"
    fi

    if announce_candidate_to_gcs "$resolved_url" "$IDENTITY_FILE" "$report_path" "$TIMEOUT_SEC" "$DRY_RUN"; then
        if [[ "$DRY_RUN" == "true" ]]; then
            log_success "Dry-run payload prepared for ${resolved_url}"
        else
            log_success "Candidate announce completed for ${resolved_url}"
            if [[ -n "$ANNOUNCE_LAST_CANDIDATE_ID" ]]; then
                echo "candidate_id=${ANNOUNCE_LAST_CANDIDATE_ID}"
            fi
            if [[ -n "$ANNOUNCE_LAST_REGISTRATION_STATE" ]]; then
                echo "registration_state=${ANNOUNCE_LAST_REGISTRATION_STATE}"
            fi
        fi
    else
        log_error "Candidate announce failed for ${resolved_url}: ${ANNOUNCE_LAST_ERROR:-unknown}"
        if [[ -n "$ANNOUNCE_LAST_MESSAGE" ]]; then
            echo "message=${ANNOUNCE_LAST_MESSAGE}"
        fi
        [[ "$REPORT_JSON" == "-" ]] && cat "$report_path"
        [[ "$REPORT_JSON" == "-" ]] && rm -f "$report_path"
        exit 1
    fi

    if [[ "$REPORT_JSON" == "-" ]]; then
        cat "$report_path"
        rm -f "$report_path"
    elif [[ -n "$REPORT_JSON" ]]; then
        log_success "Announce report written: ${REPORT_JSON}"
    fi
}

main "$@"
