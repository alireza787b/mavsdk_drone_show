#!/bin/bash
# =============================================================================
# MDS Initialization Library: Hardware Identity
# =============================================================================
# Version: 4.5.0
# Description: Hardware identity, node manifest, and local runtime configuration
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_IDENTITY_LOADED:-}" ]] && return 0
_MDS_IDENTITY_LOADED=1

# =============================================================================
# HARDWARE ID FUNCTIONS
# =============================================================================

# Remove existing hwID files
cleanup_old_hwid_files() {
    log_step "Cleaning up old hwID files..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would remove old .hwID files${NC}"
        return 0
    fi

    local count=0
    for hwid_file in "${MDS_INSTALL_DIR}"/*.hwID; do
        if [[ -f "$hwid_file" ]]; then
            rm -f "$hwid_file"
            ((count++))
        fi
    done

    if [[ $count -gt 0 ]]; then
        log_info "Removed $count old hwID file(s)"
    fi

    return 0
}

# Create hardware ID file
create_hwid_file() {
    local drone_id="$1"

    log_step "Creating hardware ID file..."

    if ! validate_drone_id "$drone_id"; then
        log_error "Invalid drone ID: $drone_id (must be 1-999)"
        return 1
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create: ${MDS_INSTALL_DIR}/${drone_id}.hwID${NC}"
        return 0
    fi

    # Remove old hwID files first
    cleanup_old_hwid_files

    # Create new hwID file
    local hwid_file="${MDS_INSTALL_DIR}/${drone_id}.hwID"
    touch "$hwid_file"
    chown "${MDS_USER}:${MDS_USER}" "$hwid_file"
    chmod 644 "$hwid_file"

    log_success "Hardware ID file created: ${drone_id}.hwID"
    state_set_value "hw_id" "$drone_id"
    return 0
}

# Create real.mode marker file
create_realmode_file() {
    log_step "Creating real.mode marker..."

    local realmode_file="${MDS_INSTALL_DIR}/real.mode"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create: ${realmode_file}${NC}"
        return 0
    fi

    if [[ -f "$realmode_file" ]]; then
        log_info "real.mode file already exists"
        return 0
    fi

    touch "$realmode_file"
    chown "${MDS_USER}:${MDS_USER}" "$realmode_file"
    chmod 644 "$realmode_file"

    log_success "real.mode marker created"
    return 0
}

# Get current hardware ID from existing file
get_current_hwid() {
    for hwid_file in "${MDS_INSTALL_DIR}"/*.hwID; do
        if [[ -f "$hwid_file" ]]; then
            basename "$hwid_file" .hwID
            return 0
        fi
    done
    echo ""
}

run_repo_git_query() {
    git -c safe.directory="${MDS_INSTALL_DIR}" -C "${MDS_INSTALL_DIR}" "$@" 2>/dev/null || \
        sudo -u "${MDS_USER}" git -C "${MDS_INSTALL_DIR}" "$@" 2>/dev/null || true
}

get_repo_origin_url() {
    run_repo_git_query config --get remote.origin.url
}

get_repo_branch() {
    local branch=""
    branch=$(run_repo_git_query branch --show-current)
    if [[ -z "$branch" ]]; then
        branch=$(state_get_value "repo_branch" "")
    fi
    if [[ -z "$branch" ]]; then
        branch=$(get_local_env_value "MDS_BRANCH" "")
    fi
    echo "$branch"
}

get_repo_commit() {
    run_repo_git_query rev-parse --short HEAD
}

# =============================================================================
# HOSTNAME CONFIGURATION
# =============================================================================

# Configure hostname
configure_hostname() {
    local drone_id="$1"
    local new_hostname="drone${drone_id}"

    log_step "Configuring hostname..."

    local current_hostname
    current_hostname=$(hostname)

    if [[ "$current_hostname" == "$new_hostname" ]]; then
        log_info "Hostname already set to: $new_hostname"
        return 0
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would set hostname: ${current_hostname} -> ${new_hostname}${NC}"
        return 0
    fi

    log_info "Changing hostname: $current_hostname -> $new_hostname"

    # Update /etc/hostname
    echo "$new_hostname" > /etc/hostname

    # Update /etc/hosts
    update_hosts_file "$current_hostname" "$new_hostname"

    # Apply hostname change
    hostnamectl set-hostname "$new_hostname" 2>/dev/null || hostname "$new_hostname"

    log_success "Hostname configured: $new_hostname"
    state_set_value "hostname" "$new_hostname"
    return 0
}

# Update /etc/hosts file
update_hosts_file() {
    local old_hostname="$1"
    local new_hostname="$2"

    log_step "Updating /etc/hosts..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would update /etc/hosts${NC}"
        return 0
    fi

    # Backup hosts file
    backup_file "/etc/hosts"

    # Remove old hostname entries if they exist
    sed -i "s/\b${old_hostname}\b/${new_hostname}/g" /etc/hosts 2>/dev/null || true

    # Ensure localhost entries exist
    if ! grep -q "127.0.0.1.*localhost" /etc/hosts; then
        echo "127.0.0.1 localhost" >> /etc/hosts
    fi

    if ! grep -q "127.0.1.1.*${new_hostname}" /etc/hosts; then
        # Add or update 127.0.1.1 entry
        if grep -q "^127.0.1.1" /etc/hosts; then
            sed -i "s/^127.0.1.1.*/127.0.1.1\t${new_hostname}/" /etc/hosts
        else
            echo -e "127.0.1.1\t${new_hostname}" >> /etc/hosts
        fi
    fi

    log_success "/etc/hosts updated"
    return 0
}

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================

# Setup local.env file
setup_local_env() {
    local drone_id="$1"
    local gcs_ip="${2:-}"
    local repo_url="${3:-}"
    local branch="${4:-}"
    local gcs_api_url="${5:-}"
    local git_auth_token_file="${MDS_GIT_AUTH_TOKEN_FILE:-}"

    log_step "Setting up local environment configuration..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would create: ${MDS_LOCAL_ENV}${NC}"
        return 0
    fi

    # Ensure config directory exists
    mkdir -p "${MDS_CONFIG_DIR}"
    chmod 755 "${MDS_CONFIG_DIR}"

    [[ -z "$repo_url" ]] && repo_url="$(get_repo_origin_url)"
    [[ -z "$branch" ]] && branch="$(get_repo_branch)"

    {
        printf '# MDS Local Configuration\n'
        printf '# Generated by mds_node_init.sh v%s on %s\n' "${MDS_VERSION}" "$(date '+%Y-%m-%d %H:%M:%S')"
        printf '# This file is loaded by params.py to override default settings\n'
        printf '# Do not commit this file to git - it contains drone-specific configuration\n\n'
        printf '# Hardware ID (required)\n'
        printf 'MDS_HW_ID=%s\n' "$drone_id"

        if [[ -n "$gcs_ip" ]]; then
            printf '\n# Ground Control Station IP override\n'
            printf 'MDS_GCS_IP=%s\n' "$gcs_ip"
        fi

        if [[ -n "$gcs_api_url" ]]; then
            printf '\n# Ground Control Station API base URL override\n'
            printf 'MDS_GCS_API_BASE_URL=%s\n' "$gcs_api_url"
        fi

        if [[ -n "$repo_url" ]]; then
            printf '\n# Repository URL override (for custom forks)\n'
            printf 'MDS_REPO_URL=%s\n' "$repo_url"
        fi

        if [[ -n "$branch" ]]; then
            printf '\n# Branch override\n'
            printf 'MDS_BRANCH=%s\n' "$branch"
        fi

        if [[ -n "$git_auth_token_file" ]]; then
            printf '\n# Preferred private HTTPS Git token file\n'
            printf 'MDS_GIT_AUTH_TOKEN_FILE=%s\n' "$git_auth_token_file"
        fi

        cat <<'EOF'

# Optional settings (uncomment to override):
# MDS_LOG_LEVEL=DEBUG
# MDS_LOG_MAX_SIZE_MB=100
# MDS_BACKUP_COUNT=20
# MDS_SIM_MODE=false
# MDS_MAVLINK_PORT=14540
# MDS_GCS_API_PORT=5000
EOF
    } > "${MDS_LOCAL_ENV}"
    chmod 644 "${MDS_LOCAL_ENV}"

    log_success "Local environment configured: ${MDS_LOCAL_ENV}"
    return 0
}

# Read value from local.env
get_local_env_value() {
    local key="$1"
    local default="${2:-}"

    if [[ -f "${MDS_LOCAL_ENV}" ]]; then
        local value
        value=$(grep "^${key}=" "${MDS_LOCAL_ENV}" 2>/dev/null | cut -d= -f2- | tr -d '"'"'" || echo "")
        [[ -n "$value" ]] && echo "$value" || echo "$default"
    else
        echo "$default"
    fi
}

# Update a value in local.env
update_local_env_value() {
    local key="$1"
    local value="$2"

    if [[ ! -f "${MDS_LOCAL_ENV}" ]]; then
        echo "${key}=${value}" > "${MDS_LOCAL_ENV}"
        return 0
    fi

    if grep -q "^${key}=" "${MDS_LOCAL_ENV}"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "${MDS_LOCAL_ENV}"
    else
        echo "${key}=${value}" >> "${MDS_LOCAL_ENV}"
    fi
}

# =============================================================================
# NODE IDENTITY MANIFEST
# =============================================================================

get_or_create_node_uuid() {
    local existing=""

    existing=$(state_get_value "node_uuid" "")
    if [[ -z "$existing" ]] && [[ -f "${MDS_NODE_IDENTITY_FILE}" ]] && command -v jq &>/dev/null; then
        existing=$(jq -r '.node_uuid // ""' "${MDS_NODE_IDENTITY_FILE}" 2>/dev/null || echo "")
    fi

    if [[ -n "$existing" ]]; then
        echo "$existing"
        return 0
    fi

    if command -v uuidgen &>/dev/null; then
        uuidgen | tr '[:upper:]' '[:lower:]'
        return 0
    fi

    if [[ -r /proc/sys/kernel/random/uuid ]]; then
        tr '[:upper:]' '[:lower:]' < /proc/sys/kernel/random/uuid
        return 0
    fi

    echo "mds-node-$(date +%s)-$$"
}

detect_network_mode() {
    local netbird_ip
    netbird_ip=$(get_effective_netbird_ip)

    if [[ -n "$netbird_ip" ]] && [[ -n "${STATIC_IP:-}" ]]; then
        echo "netbird_static_ip"
        return 0
    fi

    if [[ -n "$netbird_ip" ]]; then
        echo "netbird"
        return 0
    fi

    if [[ -n "${STATIC_IP:-}" ]]; then
        echo "static_ip"
        return 0
    fi

    echo "dhcp"
}

get_primary_control_ip() {
    local netbird_ip
    netbird_ip=$(get_effective_netbird_ip)
    if [[ -n "$netbird_ip" ]]; then
        echo "$netbird_ip"
        return 0
    fi

    local iface=""
    iface=$(detect_network_interface 2>/dev/null || echo "")
    if [[ -z "$iface" ]]; then
        echo ""
        return 0
    fi

    ip -4 addr show "$iface" 2>/dev/null | grep -oP 'inet \K[\d.]+' | head -1
}

get_effective_netbird_ip() {
    local netbird_ip
    netbird_ip=$(state_get_value "netbird_ip" "")

    if [[ -z "$netbird_ip" ]] && declare -F get_netbird_primary_ip >/dev/null 2>&1; then
        netbird_ip=$(get_netbird_primary_ip 2>/dev/null || echo "")
    fi

    if [[ -n "$netbird_ip" ]]; then
        state_set_value "netbird_ip" "$netbird_ip"
    fi

    echo "$netbird_ip"
}

detect_mavlink_routing_mode() {
    if [[ "${MAVLINK_SKIP:-false}" == "true" ]]; then
        echo "manual_external"
        return 0
    fi

    if [[ -d "${MAVLINK_ANYWHERE_DIR:-/opt/mavlink-anywhere}" ]]; then
        echo "mavlink_anywhere"
        return 0
    fi

    if [[ -f /etc/systemd/system/mavlink-router.service ]] || [[ -f /lib/systemd/system/mavlink-router.service ]]; then
        echo "mavlink_anywhere"
        return 0
    fi

    echo "manual_external"
}

detect_mavlink_input_device() {
    if [[ "${MAVLINK_INPUT_TYPE:-uart}" == "udp" ]]; then
        echo "udp:${MAVLINK_INPUT_PORT:-14550}"
        return 0
    fi

    if [[ -n "${MAVLINK_UART:-}" ]]; then
        echo "${MAVLINK_UART}"
        return 0
    fi

    detect_uart_device 2>/dev/null || echo "/dev/ttyS0"
}

write_node_identity_manifest() {
    local drone_id="${1:-${DRONE_ID:-}}"
    local bootstrap_status="${2:-identity_configured}"

    if [[ -z "$drone_id" ]]; then
        drone_id=$(state_get_value "hw_id" "")
    fi

    if [[ -z "$drone_id" ]]; then
        log_warn "Skipping node identity manifest update: hardware ID is not set yet"
        return 0
    fi

    local node_uuid hostname repo_url branch commit network_mode primary_control_ip netbird_ip
    local mavlink_routing_mode mavlink_input_type mavlink_input_device role_hint
    local netbird_enabled generated_at created_at

    node_uuid=$(get_or_create_node_uuid)
    hostname=$(hostname 2>/dev/null || echo "unknown")
    repo_url="${REPO_URL:-$(state_get_value repo_url "")}"
    [[ -z "$repo_url" ]] && repo_url="$(get_local_env_value "MDS_REPO_URL" "")"
    [[ -z "$repo_url" ]] && repo_url="$(get_repo_origin_url)"

    branch="${BRANCH:-$(state_get_value repo_branch "")}"
    [[ -z "$branch" ]] && branch="$(get_local_env_value "MDS_BRANCH" "")"
    [[ -z "$branch" ]] && branch="$(get_repo_branch)"

    commit="$(get_repo_commit)"
    netbird_ip=$(get_effective_netbird_ip)
    network_mode=$(detect_network_mode)
    primary_control_ip=$(get_primary_control_ip)
    mavlink_routing_mode=$(detect_mavlink_routing_mode)
    mavlink_input_type="${MAVLINK_INPUT_TYPE:-uart}"
    mavlink_input_device=$(detect_mavlink_input_device)
    role_hint=$(get_local_env_value "MDS_ROLE_HINT" "")
    generated_at=$(date -Iseconds)
    created_at=""

    if [[ -f "${MDS_NODE_IDENTITY_FILE}" ]] && command -v jq &>/dev/null; then
        created_at=$(jq -r '.created_at // .updated_at // ""' "${MDS_NODE_IDENTITY_FILE}" 2>/dev/null || echo "")
    fi
    [[ -z "$created_at" || "$created_at" == "null" ]] && created_at="$generated_at"

    if [[ -n "$netbird_ip" ]]; then
        netbird_enabled="true"
    else
        netbird_enabled="false"
    fi

    state_set_value "node_uuid" "$node_uuid"
    state_set_value "primary_control_ip" "$primary_control_ip"
    state_set_value "network_mode" "$network_mode"
    state_set_value "mavlink_routing_mode" "$mavlink_routing_mode"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would write: ${MDS_NODE_IDENTITY_FILE}${NC}"
        return 0
    fi

    mkdir -p "${MDS_CONFIG_DIR}"

    local tmp_file="${MDS_NODE_IDENTITY_FILE}.tmp"
    jq -n \
        --arg node_uuid "$node_uuid" \
        --arg hostname "$hostname" \
        --arg role_hint "$role_hint" \
        --arg repo_url "$repo_url" \
        --arg branch "$branch" \
        --arg commit "$commit" \
        --arg bootstrap_version "$MDS_VERSION" \
        --arg bootstrap_status "$bootstrap_status" \
        --arg network_mode "$network_mode" \
        --arg primary_control_ip "$primary_control_ip" \
        --arg mavlink_routing_mode "$mavlink_routing_mode" \
        --arg mavlink_input_type "$mavlink_input_type" \
        --arg mavlink_input_device "$mavlink_input_device" \
        --arg created_at "$created_at" \
        --arg generated_at "$generated_at" \
        --arg local_env_file "$MDS_LOCAL_ENV" \
        --arg node_identity_file "$MDS_NODE_IDENTITY_FILE" \
        --argjson hw_id "$drone_id" \
        --argjson netbird_enabled "$netbird_enabled" \
        '{
            node_uuid: $node_uuid,
            hw_id: $hw_id,
            hostname: $hostname,
            role_hint: (if $role_hint == "" then null else $role_hint end),
            repo_url: (if $repo_url == "" then null else $repo_url end),
            branch: (if $branch == "" then null else $branch end),
            commit: (if $commit == "" then null else $commit end),
            bootstrap_version: $bootstrap_version,
            bootstrap_status: $bootstrap_status,
            created_at: $created_at,
            last_bootstrap_at: $generated_at,
            network_mode: $network_mode,
            primary_control_ip: (if $primary_control_ip == "" then null else $primary_control_ip end),
            netbird_enabled: $netbird_enabled,
            mavlink_routing_mode: $mavlink_routing_mode,
            mavlink_input_type: $mavlink_input_type,
            mavlink_input_device: (if $mavlink_input_device == "" then null else $mavlink_input_device end),
            local_env_file: $local_env_file,
            node_identity_file: $node_identity_file,
            updated_at: $generated_at
        }' > "${tmp_file}" && mv "${tmp_file}" "${MDS_NODE_IDENTITY_FILE}"

    chmod 644 "${MDS_NODE_IDENTITY_FILE}"
    log_success "Node identity manifest updated: ${MDS_NODE_IDENTITY_FILE}"
    return 0
}

write_bootstrap_report() {
    local exit_code="${1:-0}"
    local report_path="${REPORT_JSON:-}"

    if [[ -z "$report_path" ]]; then
        return 0
    fi

    local status="failed"
    [[ "$exit_code" -eq 0 ]] && status="ok"

    local report_repo_url report_branch report_commit
    report_repo_url="${REPO_URL:-$(state_get_value repo_url "")}"
    [[ -z "$report_repo_url" ]] && report_repo_url="$(get_local_env_value "MDS_REPO_URL" "")"
    [[ -z "$report_repo_url" ]] && report_repo_url="$(get_repo_origin_url)"

    report_branch="${BRANCH:-$(state_get_value repo_branch "")}"
    [[ -z "$report_branch" ]] && report_branch="$(get_local_env_value "MDS_BRANCH" "")"
    [[ -z "$report_branch" ]] && report_branch="$(get_repo_branch)"

    report_commit="$(get_repo_commit)"

    local report_json
    report_json=$(jq -n \
        --arg status "$status" \
        --arg generated_at "$(date -Iseconds)" \
        --arg script_version "$MDS_VERSION" \
        --arg drone_id "${DRONE_ID:-$(state_get_value hw_id "")}" \
        --arg hostname "$(hostname 2>/dev/null || echo unknown)" \
        --arg repo_url "$report_repo_url" \
        --arg branch "$report_branch" \
        --arg commit "$report_commit" \
        --arg node_uuid "$(state_get_value node_uuid "")" \
        --arg gcs_api_url "${GCS_API_URL:-$(state_get_value announce_url "")}" \
        --arg announce_status "$(state_get_value announce_status "")" \
        --arg announce_http_status "$(state_get_value announce_http_status "")" \
        --arg announce_candidate_id "$(state_get_value announce_candidate_id "")" \
        --arg announce_registration_state "$(state_get_value announce_registration_state "")" \
        --arg announce_message "$(state_get_value announce_message "")" \
        --arg state_file "$MDS_STATE_FILE" \
        --arg local_env_file "$MDS_LOCAL_ENV" \
        --arg node_identity_file "$MDS_NODE_IDENTITY_FILE" \
        --argjson exit_code "$exit_code" \
        '{
            status: $status,
            exit_code: $exit_code,
            generated_at: $generated_at,
            script_version: $script_version,
            drone_id: (if $drone_id == "" then null else $drone_id end),
            hostname: $hostname,
            repo_url: (if $repo_url == "" then null else $repo_url end),
            branch: (if $branch == "" then null else $branch end),
            commit: (if $commit == "" then null else $commit end),
            node_uuid: (if $node_uuid == "" then null else $node_uuid end),
            gcs_api_url: (if $gcs_api_url == "" then null else $gcs_api_url end),
            announce_status: (if $announce_status == "" then null else $announce_status end),
            announce_http_status: (if $announce_http_status == "" then null else ($announce_http_status | tonumber) end),
            announce_candidate_id: (if $announce_candidate_id == "" then null else $announce_candidate_id end),
            announce_registration_state: (if $announce_registration_state == "" then null else $announce_registration_state end),
            announce_message: (if $announce_message == "" then null else $announce_message end),
            state_file: $state_file,
            local_env_file: $local_env_file,
            node_identity_file: $node_identity_file
        }'
    )

    if [[ "$report_path" == "-" ]]; then
        printf '%s\n' "$report_json"
        return 0
    fi

    mkdir -p "$(dirname "$report_path")"
    printf '%s\n' "$report_json" > "$report_path"
    chmod 644 "$report_path" 2>/dev/null || true
    log_success "Bootstrap report written: ${report_path}"
    return 0
}

# =============================================================================
# MAIN IDENTITY RUNNER
# =============================================================================

run_identity_phase() {
    local drone_id="${DRONE_ID:-}"

    print_phase_header "4" "Hardware Identity"

    # Check for existing hardware ID
    local existing_id
    existing_id=$(get_current_hwid)

    if [[ -z "$drone_id" ]]; then
        if [[ -n "$existing_id" ]]; then
            log_info "Found existing hardware ID: $existing_id"

            if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
                if confirm "Keep existing hardware ID ($existing_id)?" "y"; then
                    drone_id="$existing_id"
                else
                    prompt_input "Enter new drone ID (1-999)" "1" drone_id
                fi
            else
                drone_id="$existing_id"
            fi
        else
            if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
                log_error "Drone ID is required in non-interactive mode (use -d or --drone-id)"
                return 1
            fi

            prompt_input "Enter drone ID (1-999)" "1" drone_id
        fi
    fi

    # Validate drone ID
    if ! validate_drone_id "$drone_id"; then
        log_error "Invalid drone ID: $drone_id (must be 1-999)"
        return 1
    fi

    # Store in global for other phases
    DRONE_ID="$drone_id"
    export DRONE_ID

    # Update state
    state_set_drone_id "$drone_id"

    print_section "Hardware Identity Setup"

    # Create hwID file
    create_hwid_file "$drone_id" || return 1

    # Create real.mode marker
    create_realmode_file || return 1

    # Configure hostname
    configure_hostname "$drone_id" || return 1

    print_section "Environment Configuration"

    # Setup local.env
    setup_local_env "$drone_id" "${GCS_IP:-}" "${REPO_URL:-}" "${BRANCH:-}" "${GCS_API_URL:-}" || return 1
    write_node_identity_manifest "$drone_id" "identity_configured" || return 1

    echo ""
    log_success "Hardware identity configured for Drone $drone_id"
    return 0
}
