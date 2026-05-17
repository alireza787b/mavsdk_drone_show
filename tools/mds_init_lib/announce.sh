#!/bin/bash
# =============================================================================
# MDS Initialization Library: Candidate Announce
# =============================================================================
# Version: Reads from VERSION file via common.sh
# Description: Canonical node -> GCS candidate announce helpers
# =============================================================================

[[ -n "${_MDS_ANNOUNCE_LOADED:-}" ]] && return 0
_MDS_ANNOUNCE_LOADED=1

readonly DEFAULT_GCS_API_PORT="${MDS_DEFAULT_GCS_API_PORT:-5030}"
readonly DEFAULT_ANNOUNCE_TIMEOUT_SEC="15"

ANNOUNCE_LAST_STATUS=""
ANNOUNCE_LAST_HTTP_STATUS=""
ANNOUNCE_LAST_URL=""
ANNOUNCE_LAST_MESSAGE=""
ANNOUNCE_LAST_CANDIDATE_ID=""
ANNOUNCE_LAST_REGISTRATION_STATE=""
ANNOUNCE_LAST_ERROR=""

reset_announce_result() {
    ANNOUNCE_LAST_STATUS=""
    ANNOUNCE_LAST_HTTP_STATUS=""
    ANNOUNCE_LAST_URL=""
    ANNOUNCE_LAST_MESSAGE=""
    ANNOUNCE_LAST_CANDIDATE_ID=""
    ANNOUNCE_LAST_REGISTRATION_STATE=""
    ANNOUNCE_LAST_ERROR=""
}

read_key_value_file() {
    local file_path="$1"
    local key="$2"

    if [[ ! -f "$file_path" ]]; then
        return 1
    fi

    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        if [[ "$line" == "${key}="* ]]; then
            printf '%s\n' "${line#*=}"
            return 0
        fi
    done < "$file_path"

    return 1
}

normalize_api_base_url() {
    local raw="${1:-}"
    raw="${raw%/}"
    raw="${raw%/api/v1/fleet/candidates/announce}"
    raw="${raw%/api/v1}"
    raw="${raw%/api}"
    printf '%s\n' "$raw"
}

format_api_host_for_url() {
    local host="${1:-}"
    if [[ "$host" == *":"* ]] && [[ "$host" != \[*\]* ]]; then
        printf '[%s]\n' "$host"
        return 0
    fi
    printf '%s\n' "$host"
}

resolve_gcs_api_base_url() {
    local explicit_url="${1:-}"
    local local_env_path="${2:-${MDS_LOCAL_ENV}}"
    local base_url=""
    local host=""
    local port=""

    if [[ -n "$explicit_url" ]]; then
        base_url="$explicit_url"
    elif [[ -n "${MDS_GCS_API_BASE_URL:-}" ]]; then
        base_url="${MDS_GCS_API_BASE_URL}"
    else
        base_url="$(read_key_value_file "$local_env_path" "MDS_GCS_API_BASE_URL" 2>/dev/null || true)"
    fi

    if [[ -n "$base_url" ]]; then
        normalize_api_base_url "$base_url"
        return 0
    fi

    if [[ -n "${GCS_IP:-}" ]]; then
        host="${GCS_IP}"
    elif [[ -n "${MDS_GCS_IP:-}" ]]; then
        host="${MDS_GCS_IP}"
    else
        host="$(read_key_value_file "$local_env_path" "MDS_GCS_IP" 2>/dev/null || true)"
    fi

    if [[ -z "$host" ]]; then
        return 1
    fi

    if [[ -n "${MDS_GCS_API_PORT:-}" ]]; then
        port="${MDS_GCS_API_PORT}"
    else
        port="$(read_key_value_file "$local_env_path" "MDS_GCS_API_PORT" 2>/dev/null || true)"
    fi
    port="${port:-${DEFAULT_GCS_API_PORT}}"

    host="$(format_api_host_for_url "$host")"
    normalize_api_base_url "http://${host}:${port}"
}

read_gcs_api_token() {
    local local_env_path="${1:-${MDS_LOCAL_ENV}}"
    local token_file=""
    local token=""

    if [[ -n "${MDS_GCS_API_TOKEN_FILE:-}" ]]; then
        token_file="${MDS_GCS_API_TOKEN_FILE}"
    else
        token_file="$(read_key_value_file "$local_env_path" "MDS_GCS_API_TOKEN_FILE" 2>/dev/null || true)"
    fi

    if [[ -z "$token_file" || ! -r "$token_file" ]]; then
        return 1
    fi

    token="$(tr -d '\r\n' < "$token_file")"
    [[ -n "$token" ]] || return 1
    printf '%s\n' "$token"
}

determine_bootstrap_status_for_announce() {
    if [[ -f "${MDS_STATE_FILE:-}" ]] && command_exists jq; then
        if jq -e '.phases | to_entries | map(select(.key != "candidate_announce")) | any(.value.status == "failed")' "${MDS_STATE_FILE}" >/dev/null 2>&1; then
            printf 'completed_with_errors\n'
            return 0
        fi
    fi
    printf 'completed\n'
}

build_candidate_announce_payload() {
    local identity_file="${1:-${MDS_NODE_IDENTITY_FILE}}"
    local payload_path="${2:-}"
    local timestamp_ms

    if [[ ! -f "$identity_file" ]]; then
        echo "Node identity manifest not found: ${identity_file}" >&2
        return 1
    fi

    if ! command_exists jq; then
        echo "jq is required to build the candidate announce payload" >&2
        return 1
    fi

    timestamp_ms=$(( $(date +%s) * 1000 ))

    local jq_filter
    jq_filter='{
        node_uuid,
        runtime_mode: (.runtime_mode // .mode),
        hw_id,
        hostname,
        role_hint,
        repo_url,
        branch,
        commit,
        bootstrap_version,
        bootstrap_status,
        network_mode,
        primary_control_ip,
        mavlink_routing_mode,
        mavlink_input_type,
        mavlink_input_device,
        timestamp: $timestamp
    } | with_entries(select(.value != null and .value != ""))'

    if [[ -n "$payload_path" ]]; then
        jq --argjson timestamp "$timestamp_ms" "$jq_filter" "$identity_file" > "$payload_path"
    else
        jq --argjson timestamp "$timestamp_ms" "$jq_filter" "$identity_file"
    fi
}

write_candidate_announce_report() {
    local report_path="$1"
    local status="$2"
    local gcs_api_url="$3"
    local endpoint="$4"
    local identity_file="$5"
    local payload_file="$6"
    local http_status="${7:-}"
    local error_message="${8:-}"
    local response_file="${9:-}"

    [[ -z "$report_path" ]] && return 0

    local candidate_id=""
    local registration_state=""
    local message=""
    local response_text=""
    local response_mode="text"

    if [[ -n "${response_file}" && -s "${response_file}" ]]; then
        if jq empty "${response_file}" >/dev/null 2>&1; then
            candidate_id="$(jq -r '.candidate.candidate_id // .candidate_id // ""' "${response_file}" 2>/dev/null || true)"
            registration_state="$(jq -r '.candidate.registration_state // .registration_state // ""' "${response_file}" 2>/dev/null || true)"
            message="$(jq -r '.message // .detail // ""' "${response_file}" 2>/dev/null || true)"
            response_mode="json"
        else
            response_text="$(cat "${response_file}")"
        fi
    fi

    mkdir -p "$(dirname "$report_path")"

    if [[ "$response_mode" == "json" ]]; then
        jq -n \
            --arg status "$status" \
            --arg generated_at "$(date -Iseconds)" \
            --arg gcs_api_url "$gcs_api_url" \
            --arg endpoint "$endpoint" \
            --arg identity_file "$identity_file" \
            --arg http_status "$http_status" \
            --arg error_message "$error_message" \
            --arg candidate_id "$candidate_id" \
            --arg registration_state "$registration_state" \
            --arg message "$message" \
            --slurpfile payload "$payload_file" \
            --slurpfile response "$response_file" \
            '{
                status: $status,
                generated_at: $generated_at,
                gcs_api_url: $gcs_api_url,
                endpoint: $endpoint,
                identity_file: $identity_file,
                http_status: (if $http_status == "" then null else ($http_status | tonumber) end),
                error: (if $error_message == "" then null else $error_message end),
                candidate_id: (if $candidate_id == "" then null else $candidate_id end),
                registration_state: (if $registration_state == "" then null else $registration_state end),
                message: (if $message == "" then null else $message end),
                payload: ($payload[0] // null),
                response: ($response[0] // null)
            }' > "$report_path"
    else
        jq -n \
            --arg status "$status" \
            --arg generated_at "$(date -Iseconds)" \
            --arg gcs_api_url "$gcs_api_url" \
            --arg endpoint "$endpoint" \
            --arg identity_file "$identity_file" \
            --arg http_status "$http_status" \
            --arg error_message "$error_message" \
            --arg response_text "$response_text" \
            --slurpfile payload "$payload_file" \
            '{
                status: $status,
                generated_at: $generated_at,
                gcs_api_url: $gcs_api_url,
                endpoint: $endpoint,
                identity_file: $identity_file,
                http_status: (if $http_status == "" then null else ($http_status | tonumber) end),
                error: (if $error_message == "" then null else $error_message end),
                payload: ($payload[0] // null),
                response_text: (if $response_text == "" then null else $response_text end)
            }' > "$report_path"
    fi

    chmod 644 "$report_path" 2>/dev/null || true
}

announce_candidate_to_gcs() {
    local gcs_api_url="$1"
    local identity_file="${2:-${MDS_NODE_IDENTITY_FILE}}"
    local report_path="${3:-}"
    local timeout_sec="${4:-${DEFAULT_ANNOUNCE_TIMEOUT_SEC}}"
    local dry_run="${5:-false}"

    reset_announce_result

    if ! command_exists curl; then
        ANNOUNCE_LAST_STATUS="failed"
        ANNOUNCE_LAST_ERROR="curl_missing"
        return 1
    fi

    if ! command_exists jq; then
        ANNOUNCE_LAST_STATUS="failed"
        ANNOUNCE_LAST_ERROR="jq_missing"
        return 1
    fi

    local resolved_url endpoint payload_file response_file
    resolved_url="$(normalize_api_base_url "$gcs_api_url")"
    endpoint="${resolved_url}/api/v1/fleet/candidates/announce"
    payload_file="$(mktemp)"
    response_file="$(mktemp)"
    ANNOUNCE_LAST_URL="$resolved_url"

    if ! build_candidate_announce_payload "$identity_file" "$payload_file"; then
        rm -f "$payload_file" "$response_file"
        ANNOUNCE_LAST_STATUS="failed"
        ANNOUNCE_LAST_ERROR="payload_build_failed"
        write_candidate_announce_report "$report_path" "failed" "$resolved_url" "$endpoint" "$identity_file" "$payload_file" "" "$ANNOUNCE_LAST_ERROR" "$response_file"
        return 1
    fi

    if [[ "$dry_run" == "true" ]]; then
        ANNOUNCE_LAST_STATUS="dry_run"
        ANNOUNCE_LAST_MESSAGE="candidate announce dry-run only"
        write_candidate_announce_report "$report_path" "dry_run" "$resolved_url" "$endpoint" "$identity_file" "$payload_file" "" "" "$response_file"
        rm -f "$payload_file" "$response_file"
        return 0
    fi

    local curl_rc=0 http_status=""
    local curl_config_file=""
    local token=""
    token="$(read_gcs_api_token "${MDS_LOCAL_ENV:-}" 2>/dev/null || true)"
    if [[ -n "$token" ]]; then
        curl_config_file="$(mktemp)"
        chmod 600 "$curl_config_file" 2>/dev/null || true
        printf 'header = "Authorization: Bearer %s"\n' "$token" > "$curl_config_file"
    fi

    local curl_auth_args=()
    if [[ -n "$curl_config_file" ]]; then
        curl_auth_args=(--config "$curl_config_file")
    fi

    http_status=$(curl -sS \
        --connect-timeout 5 \
        --max-time "$timeout_sec" \
        -o "$response_file" \
        -w '%{http_code}' \
        "${curl_auth_args[@]}" \
        -H 'Content-Type: application/json' \
        -X POST \
        --data-binary "@${payload_file}" \
        "$endpoint") || curl_rc=$?

    rm -f "$curl_config_file"

    ANNOUNCE_LAST_HTTP_STATUS="$http_status"

    if [[ "$curl_rc" -ne 0 ]]; then
        ANNOUNCE_LAST_STATUS="failed"
        ANNOUNCE_LAST_ERROR="curl_exit_${curl_rc}"
        write_candidate_announce_report "$report_path" "failed" "$resolved_url" "$endpoint" "$identity_file" "$payload_file" "$http_status" "$ANNOUNCE_LAST_ERROR" "$response_file"
        rm -f "$payload_file" "$response_file"
        return 1
    fi

    if [[ ! "$http_status" =~ ^2[0-9][0-9]$ ]]; then
        ANNOUNCE_LAST_STATUS="failed"
        ANNOUNCE_LAST_ERROR="http_${http_status}"
        if [[ -s "$response_file" ]] && jq empty "$response_file" >/dev/null 2>&1; then
            ANNOUNCE_LAST_MESSAGE="$(jq -r '.detail // .message // ""' "$response_file" 2>/dev/null || true)"
        fi
        write_candidate_announce_report "$report_path" "failed" "$resolved_url" "$endpoint" "$identity_file" "$payload_file" "$http_status" "$ANNOUNCE_LAST_ERROR" "$response_file"
        rm -f "$payload_file" "$response_file"
        return 1
    fi

    ANNOUNCE_LAST_STATUS="ok"
    if [[ -s "$response_file" ]] && jq empty "$response_file" >/dev/null 2>&1; then
        ANNOUNCE_LAST_CANDIDATE_ID="$(jq -r '.candidate.candidate_id // .candidate_id // ""' "$response_file" 2>/dev/null || true)"
        ANNOUNCE_LAST_REGISTRATION_STATE="$(jq -r '.candidate.registration_state // .registration_state // ""' "$response_file" 2>/dev/null || true)"
        ANNOUNCE_LAST_MESSAGE="$(jq -r '.message // ""' "$response_file" 2>/dev/null || true)"
    fi
    write_candidate_announce_report "$report_path" "ok" "$resolved_url" "$endpoint" "$identity_file" "$payload_file" "$http_status" "" "$response_file"
    rm -f "$payload_file" "$response_file"
    return 0
}

run_candidate_announce_phase() {
    print_phase_header "15" "Candidate Announce"

    local bootstrap_status
    bootstrap_status="$(determine_bootstrap_status_for_announce)"
    write_node_identity_manifest "${DRONE_ID:-$(state_get_value hw_id "")}" "${bootstrap_status}" || true

    local gcs_api_url
    gcs_api_url="$(resolve_gcs_api_base_url "${GCS_API_URL:-}" "${MDS_LOCAL_ENV}" 2>/dev/null || true)"
    if [[ -z "$gcs_api_url" ]]; then
        log_warn "Skipping candidate announce: no GCS API URL or GCS IP is configured"
        state_set_value "announce_status" "skipped"
        state_set_value "announce_message" "no_gcs_api_url"
        return 0
    fi

    if [[ ! -f "${MDS_NODE_IDENTITY_FILE}" ]]; then
        log_warn "Skipping candidate announce: node identity manifest is missing"
        state_set_value "announce_status" "skipped"
        state_set_value "announce_message" "missing_node_identity"
        state_set_value "announce_url" "$gcs_api_url"
        return 0
    fi

    if announce_candidate_to_gcs "$gcs_api_url" "${MDS_NODE_IDENTITY_FILE}" "${ANNOUNCE_REPORT_JSON:-}" "${ANNOUNCE_TIMEOUT_SEC:-${DEFAULT_ANNOUNCE_TIMEOUT_SEC}}" "${DRY_RUN:-false}"; then
        state_set_value "announce_status" "${ANNOUNCE_LAST_STATUS}"
        state_set_value "announce_url" "${ANNOUNCE_LAST_URL}"
        state_set_value "announce_http_status" "${ANNOUNCE_LAST_HTTP_STATUS}"
        state_set_value "announce_candidate_id" "${ANNOUNCE_LAST_CANDIDATE_ID}"
        state_set_value "announce_registration_state" "${ANNOUNCE_LAST_REGISTRATION_STATE}"
        state_set_value "announce_message" "${ANNOUNCE_LAST_MESSAGE}"

        if [[ "${ANNOUNCE_LAST_STATUS}" == "dry_run" ]]; then
            log_success "Candidate announce dry-run prepared for ${ANNOUNCE_LAST_URL}"
        else
            log_success "Candidate announce accepted by GCS (${ANNOUNCE_LAST_REGISTRATION_STATE:-unknown})"
        fi
        return 0
    fi

    state_set_value "announce_status" "failed"
    state_set_value "announce_url" "${ANNOUNCE_LAST_URL}"
    state_set_value "announce_http_status" "${ANNOUNCE_LAST_HTTP_STATUS}"
    state_set_value "announce_message" "${ANNOUNCE_LAST_MESSAGE}"
    state_set_value "announce_error" "${ANNOUNCE_LAST_ERROR}"
    log_warn "Candidate announce did not complete cleanly (${ANNOUNCE_LAST_ERROR:-unknown}). Re-run later with sudo ./tools/mds_node_announce.sh"
    return 0
}
