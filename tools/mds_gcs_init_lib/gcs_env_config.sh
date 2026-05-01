#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Environment Configuration
# =============================================================================
# Version: 1.0.0
# Description: Configure .env files for GCS operation
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_ENV_CONFIG_LOADED:-}" ]] && return 0
_MDS_GCS_ENV_CONFIG_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly GCS_DASHBOARD_ENV_EXAMPLE=".env.example"
readonly GCS_DASHBOARD_ENV=".env"

get_existing_gcs_env_value() {
    local key="$1"
    local env_file="${2:-$GCS_CONFIG_FILE}"

    if [[ ! -f "$env_file" ]]; then
        return 1
    fi

    awk -F= -v target="$key" '$1 == target {print substr($0, index($0, "=") + 1); exit}' "$env_file"
}

normalize_env_bool() {
    local value="${1:-}"
    local default="${2:-false}"

    case "${value,,}" in
        1|true|yes|on|enabled) echo "true" ;;
        0|false|no|off|disabled) echo "false" ;;
        *) echo "$default" ;;
    esac
}

clamp_auth_ttl_hours() {
    local ttl="${1:-12}"
    if [[ ! "$ttl" =~ ^[0-9]+$ ]]; then
        echo "12"
        return 0
    fi
    if (( ttl < 1 )); then
        echo "1"
    elif (( ttl > 720 )); then
        echo "720"
    else
        echo "$ttl"
    fi
}

gcs_auth_python_bin() {
    local install_dir="$1"
    if [[ -x "${install_dir}/venv/bin/python" ]]; then
        echo "${install_dir}/venv/bin/python"
    elif [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
        echo "${VIRTUAL_ENV}/bin/python"
    else
        echo "python3"
    fi
}

configure_gcs_initial_admin_user() {
    local auth_enabled="$1"
    local install_dir="$2"
    local admin_user="$3"
    local password_file="$4"
    local prompted_password="${5:-}"

    if [[ "$auth_enabled" != "true" ]]; then
        return 0
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would ensure first auth admin user exists${NC}"
        return 0
    fi

    local auth_tool="${install_dir}/tools/mds_auth_admin.py"
    if [[ ! -f "$auth_tool" ]]; then
        log_warn "Auth admin helper not found at ${auth_tool}. Create the first admin manually after bootstrap."
        return 0
    fi

    local python_bin
    python_bin=$(gcs_auth_python_bin "$install_dir")

    if [[ -n "$password_file" ]]; then
        if [[ ! -r "$password_file" ]]; then
            log_error "Auth admin password file is not readable: ${password_file}"
            return 1
        fi
        if ! MDS_GCS_SYSTEM_CONFIG="$GCS_CONFIG_FILE" "$python_bin" "$auth_tool" add-user "$admin_user" --role admin --password-file "$password_file" >/dev/null; then
            log_error "Failed to configure dashboard auth admin user. Check ${auth_tool} dependencies and ${GCS_CONFIG_FILE}."
            return 1
        fi
        log_success "Dashboard auth admin user is configured: ${admin_user}"
        return 0
    fi

    if [[ -n "$prompted_password" ]]; then
        if ! printf '%s\n' "$prompted_password" | MDS_GCS_SYSTEM_CONFIG="$GCS_CONFIG_FILE" "$python_bin" "$auth_tool" add-user "$admin_user" --role admin --password-stdin >/dev/null; then
            log_error "Failed to configure dashboard auth admin user. Check ${auth_tool} dependencies and ${GCS_CONFIG_FILE}."
            return 1
        fi
        log_success "Dashboard auth admin user is configured: ${admin_user}"
        return 0
    fi

    log_warn "Dashboard auth is enabled, but no admin password was supplied."
    echo -e "  ${DIM}Create or reset the first admin with:${NC}"
    echo -e "  ${GREEN}sudo ${python_bin} ${auth_tool} add-user ${admin_user} --role admin${NC}"
    return 0
}

# =============================================================================
# DASHBOARD .env CONFIGURATION
# =============================================================================

# Get dashboard .env path
get_dashboard_env_path() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)
    echo "${dashboard_path}/${GCS_DASHBOARD_ENV}"
}

# Get dashboard .env.example path
get_dashboard_env_example_path() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)
    echo "${dashboard_path}/${GCS_DASHBOARD_ENV_EXAMPLE}"
}

# Configure dashboard .env
configure_dashboard_env() {
    local dashboard_path
    dashboard_path=$(get_dashboard_path)
    local env_file
    env_file=$(get_dashboard_env_path)
    local env_example
    env_example=$(get_dashboard_env_example_path)

    log_step "Configuring dashboard .env..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would configure: $env_file${NC}"
        return 0
    fi

    # Check if .env already exists
    if [[ -f "$env_file" ]]; then
        log_info ".env already exists"

        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if ! confirm "Reconfigure .env file?" "n"; then
                log_info "Keeping existing .env"
                return 0
            fi
            # Backup existing
            backup_file "$env_file"
        else
            log_info "Keeping existing .env (non-interactive mode)"
            return 0
        fi
    fi

    # Copy from .env.example if it exists
    if [[ -f "$env_example" ]]; then
        cp "$env_example" "$env_file"
        log_info "Copied from .env.example"
    else
        # Create minimal .env
        cat > "$env_file" << 'EOF'
# MDS Dashboard Configuration
# Generated by mds_gcs_init.sh

# Mapbox Token (optional - for map features)
# Get a free token at https://www.mapbox.com/
REACT_APP_MAPBOX_ACCESS_TOKEN=

# Optional advanced override if dashboard and GCS run on different hosts:
# REACT_APP_MDS_SERVER_URL=
EOF
        log_info "Created new .env file"
    fi

    # Prompt for Mapbox token
    if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
        echo ""
        echo -e "  ${WHITE}Mapbox Token Configuration${NC}"
        echo -e "  ${DIM}───────────────────────────────────────────────────────────────${NC}"
        echo -e "  Mapbox provides map tiles for the dashboard."
        echo -e "  Get a free token at: ${CYAN}https://www.mapbox.com/${NC}"
        echo ""

        local mapbox_token=""
        prompt_input "Mapbox token (leave empty to skip)" "" mapbox_token

        if [[ -n "$mapbox_token" ]]; then
            # Update the token in .env (escape special characters for sed)
            local escaped_token
            escaped_token=$(printf '%s\n' "$mapbox_token" | sed -e 's/[\/&|]/\\&/g')
            sed -i "s|^REACT_APP_MAPBOX_ACCESS_TOKEN=.*|REACT_APP_MAPBOX_ACCESS_TOKEN=${escaped_token}|" "$env_file"
            log_success "Mapbox token configured"
        else
            log_info "Mapbox token skipped (can be added later)"
        fi
    fi

    log_success "Dashboard .env configured"
    return 0
}

# =============================================================================
# SYSTEM .env CONFIGURATION
# =============================================================================

# Configure GCS system environment file
configure_gcs_env() {
    log_step "Configuring system GCS environment..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would configure: ${GCS_CONFIG_FILE}${NC}"
        return 0
    fi

    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local repo_url
    repo_url=$(gcs_state_get_value "repo_url" "$GCS_DEFAULT_REPO_SSH")
    local repo_branch
    repo_branch=$(gcs_state_get_value "repo_branch" "$GCS_DEFAULT_BRANCH")
    local gcs_api_port="${MDS_DEFAULT_GCS_API_PORT:-5030}"
    local dashboard_port="${MDS_DEFAULT_DASHBOARD_PORT:-3030}"
    local git_auth_token_file="${MDS_GIT_AUTH_TOKEN_FILE:-}"
    local git_ssh_key_file="${MDS_GIT_SSH_KEY_FILE:-}"
    local auth_enabled
    auth_enabled=$(normalize_env_bool "${AUTH_ENABLED:-${MDS_AUTH_ENABLED:-false}}" "false")
    local api_auth_enabled
    api_auth_enabled=$(normalize_env_bool "${API_AUTH_ENABLED:-${MDS_API_AUTH_ENABLED:-false}}" "false")
    local auth_admin_user="${AUTH_ADMIN_USER:-${MDS_AUTH_ADMIN_USER:-admin}}"
    local auth_admin_password_file="${AUTH_ADMIN_PASSWORD_FILE:-${MDS_AUTH_ADMIN_PASSWORD_FILE:-}}"
    local auth_session_ttl_hours
    auth_session_ttl_hours=$(clamp_auth_ttl_hours "${AUTH_SESSION_TTL_HOURS:-${MDS_AUTH_SESSION_TTL_HOURS:-12}}")
    local auth_secure_cookies
    auth_secure_cookies=$(normalize_env_bool "${AUTH_SECURE_COOKIES:-${MDS_AUTH_SECURE_COOKIES:-false}}" "false")
    local auth_users_file="${MDS_AUTH_USERS_FILE:-/etc/mds/auth/users.json}"
    local api_tokens_file="${MDS_API_TOKENS_FILE:-/etc/mds/auth/api_tokens.json}"
    local auth_session_secret_file="${MDS_AUTH_SESSION_SECRET_FILE:-/etc/mds/auth/session_secret}"
    local auth_csrf_secret_file="${MDS_AUTH_CSRF_SECRET_FILE:-/etc/mds/auth/csrf_secret}"
    local auth_csrf_enabled
    auth_csrf_enabled=$(normalize_env_bool "${MDS_AUTH_CSRF_ENABLED:-true}" "true")
    local auth_allowed_cidrs="${MDS_AUTH_ALLOWED_CIDRS:-}"
    local auth_trusted_proxy_cidrs="${MDS_AUTH_TRUSTED_PROXY_CIDRS:-}"
    local prompted_auth_password=""
    local access_method
    access_method=$(gcs_state_get_value "access_method" "ssh")
    local git_auto_push="true"
    if [[ "$access_method" == "https" ]]; then
        git_auto_push="false"
    fi

    if can_prompt; then
        if confirm "Enable dashboard username/password login?" "$( [[ "$auth_enabled" == "true" ]] && echo "y" || echo "n" )"; then
            auth_enabled="true"
        else
            auth_enabled="false"
        fi

        if [[ "$auth_enabled" == "true" ]]; then
            if confirm "Require bearer tokens for drone/agent machine API endpoints?" "$( [[ "$api_auth_enabled" == "true" ]] && echo "y" || echo "n" )"; then
                api_auth_enabled="true"
            else
                api_auth_enabled="false"
            fi
            prompt_input "First admin username" "$auth_admin_user" auth_admin_user
            if [[ -z "$auth_admin_password_file" ]]; then
                prompt_input "First admin password (leave empty to manage later by SSH)" "" prompted_auth_password true
            fi
        else
            api_auth_enabled="false"
        fi
    elif [[ "$auth_enabled" != "true" ]]; then
        api_auth_enabled="false"
    fi

    # Create /etc/mds directory if needed
    mkdir -p "$(dirname "$GCS_CONFIG_FILE")"

    local existing_repo_url=""
    local existing_repo_branch=""
    local existing_git_auto_push=""
    local existing_git_auth_token_file=""
    local existing_git_ssh_key_file=""
    local existing_install_dir=""
    local existing_mode=""
    local existing_gcs_api_port=""
    local existing_dashboard_port=""
    local existing_auth_enabled=""
    local existing_api_auth_enabled=""
    local existing_auth_users_file=""
    local existing_api_tokens_file=""
    local existing_auth_session_ttl_hours=""
    local existing_auth_secure_cookies=""
    local existing_venv_path=""
    local retired_keys_present="false"
    local config_matches="false"

    if [[ -f "$GCS_CONFIG_FILE" ]]; then
        if grep -Eq '^(GCS_PORT|DASHBOARD_PORT|GCS_BACKEND|VENV_PATH)=' "$GCS_CONFIG_FILE"; then
            retired_keys_present="true"
        fi
        existing_repo_url=$(get_existing_gcs_env_value "MDS_REPO_URL" "$GCS_CONFIG_FILE" || true)
        existing_repo_branch=$(get_existing_gcs_env_value "MDS_BRANCH" "$GCS_CONFIG_FILE" || true)
        existing_git_auto_push=$(get_existing_gcs_env_value "MDS_GIT_AUTO_PUSH" "$GCS_CONFIG_FILE" || true)
        existing_git_auth_token_file=$(get_existing_gcs_env_value "MDS_GIT_AUTH_TOKEN_FILE" "$GCS_CONFIG_FILE" || true)
        existing_git_ssh_key_file=$(get_existing_gcs_env_value "MDS_GIT_SSH_KEY_FILE" "$GCS_CONFIG_FILE" || true)
        existing_install_dir=$(get_existing_gcs_env_value "MDS_INSTALL_DIR" "$GCS_CONFIG_FILE" || true)
        existing_mode=$(get_existing_gcs_env_value "MDS_MODE" "$GCS_CONFIG_FILE" || true)
        existing_gcs_api_port=$(get_existing_gcs_env_value "MDS_GCS_API_PORT" "$GCS_CONFIG_FILE" || true)
        existing_dashboard_port=$(get_existing_gcs_env_value "MDS_DASHBOARD_PORT" "$GCS_CONFIG_FILE" || true)
        existing_auth_enabled=$(get_existing_gcs_env_value "MDS_AUTH_ENABLED" "$GCS_CONFIG_FILE" || true)
        existing_api_auth_enabled=$(get_existing_gcs_env_value "MDS_API_AUTH_ENABLED" "$GCS_CONFIG_FILE" || true)
        existing_auth_users_file=$(get_existing_gcs_env_value "MDS_AUTH_USERS_FILE" "$GCS_CONFIG_FILE" || true)
        existing_api_tokens_file=$(get_existing_gcs_env_value "MDS_API_TOKENS_FILE" "$GCS_CONFIG_FILE" || true)
        existing_auth_session_ttl_hours=$(get_existing_gcs_env_value "MDS_AUTH_SESSION_TTL_HOURS" "$GCS_CONFIG_FILE" || true)
        existing_auth_secure_cookies=$(get_existing_gcs_env_value "MDS_AUTH_SECURE_COOKIES" "$GCS_CONFIG_FILE" || true)
        existing_venv_path=$(get_existing_gcs_env_value "MDS_VENV_PATH" "$GCS_CONFIG_FILE" || true)

        if [[ "$existing_repo_url" == "$repo_url" ]] && \
           [[ "$existing_repo_branch" == "$repo_branch" ]] && \
           [[ "$existing_git_auto_push" == "$git_auto_push" ]] && \
           [[ "$existing_git_auth_token_file" == "$git_auth_token_file" ]] && \
           [[ "$existing_git_ssh_key_file" == "$git_ssh_key_file" ]] && \
           [[ "$existing_install_dir" == "$install_dir" ]] && \
           [[ "$existing_gcs_api_port" == "$gcs_api_port" ]] && \
           [[ "$existing_dashboard_port" == "$dashboard_port" ]] && \
           [[ "${existing_venv_path:-${install_dir}/venv}" == "${install_dir}/venv" ]] && \
           [[ "$retired_keys_present" == "false" ]] && \
           [[ "$existing_mode" == "real" ]] && \
           [[ "$(normalize_env_bool "$existing_auth_enabled" "false")" == "$auth_enabled" ]] && \
           [[ "$(normalize_env_bool "$existing_api_auth_enabled" "false")" == "$api_auth_enabled" ]] && \
           [[ "${existing_auth_users_file:-/etc/mds/auth/users.json}" == "$auth_users_file" ]] && \
           [[ "${existing_api_tokens_file:-/etc/mds/auth/api_tokens.json}" == "$api_tokens_file" ]] && \
           [[ "${existing_auth_session_ttl_hours:-12}" == "$auth_session_ttl_hours" ]] && \
           [[ "$(normalize_env_bool "$existing_auth_secure_cookies" "false")" == "$auth_secure_cookies" ]]; then
            config_matches="true"
        fi
    fi

    # Check if file exists
    if [[ -f "$GCS_CONFIG_FILE" ]]; then
        if [[ "$config_matches" == "true" ]]; then
            log_info "GCS configuration already matches requested repo, branch, ports, and runtime mode"
            configure_gcs_initial_admin_user "$auth_enabled" "$install_dir" "$auth_admin_user" "$auth_admin_password_file" "$prompted_auth_password" || return 1
            return 0
        fi

        if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
            if ! confirm "Reconfigure ${GCS_CONFIG_FILE}?" "n"; then
                log_info "Keeping existing GCS configuration"
                return 0
            fi
            backup_file "$GCS_CONFIG_FILE"
        else
            backup_file "$GCS_CONFIG_FILE"
            log_info "Updating existing GCS configuration to match requested repo and branch"
        fi
    fi

    # Create GCS config file
    cat > "$GCS_CONFIG_FILE" << EOF
# MDS GCS Configuration
# Generated by mds_gcs_init.sh on $(date -Iseconds)

# GCS Server Settings
MDS_GCS_API_PORT=${gcs_api_port}
MDS_MODE=real

# Repository Settings
MDS_REPO_URL=${repo_url}
MDS_BRANCH=${repo_branch}
MDS_GIT_AUTO_PUSH=${git_auto_push}
MDS_GIT_AUTH_TOKEN_FILE=${git_auth_token_file}
MDS_GIT_SSH_KEY_FILE=${git_ssh_key_file}
MDS_INSTALL_DIR=${install_dir}

# Dashboard Settings
MDS_DASHBOARD_PORT=${dashboard_port}

# Optional Dashboard/API Auth
MDS_AUTH_ENABLED=${auth_enabled}
MDS_API_AUTH_ENABLED=${api_auth_enabled}
MDS_AUTH_USERS_FILE=${auth_users_file}
MDS_API_TOKENS_FILE=${api_tokens_file}
MDS_AUTH_SESSION_SECRET_FILE=${auth_session_secret_file}
MDS_AUTH_CSRF_SECRET_FILE=${auth_csrf_secret_file}
MDS_AUTH_SESSION_TTL_HOURS=${auth_session_ttl_hours}
MDS_AUTH_SECURE_COOKIES=${auth_secure_cookies}
MDS_AUTH_CSRF_ENABLED=${auth_csrf_enabled}
MDS_AUTH_ALLOWED_CIDRS=${auth_allowed_cidrs}
MDS_AUTH_TRUSTED_PROXY_CIDRS=${auth_trusted_proxy_cidrs}

# Virtual Environment
MDS_VENV_PATH=${install_dir}/venv
EOF

    chmod 644 "$GCS_CONFIG_FILE"
    log_success "GCS system configuration created: ${GCS_CONFIG_FILE}"
    configure_gcs_initial_admin_user "$auth_enabled" "$install_dir" "$auth_admin_user" "$auth_admin_password_file" "$prompted_auth_password" || return 1
    if [[ "$git_auto_push" == "false" ]]; then
        log_info "Set MDS_GIT_AUTO_PUSH=false because this GCS is configured with an HTTPS/read-only repository."
    fi

    return 0
}

# =============================================================================
# DASHBOARD ENV CLEANUP
# =============================================================================

# Remove obsolete dashboard env keys so fresh installs have one frontend URL contract.
cleanup_dashboard_env() {
    local env_file
    env_file=$(get_dashboard_env_path)

    log_step "Cleaning dashboard environment..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would clean dashboard env${NC}"
        return 0
    fi

    if [[ ! -f "$env_file" ]]; then
        return 0
    fi

    if grep -q "^REACT_APP_SERVER_URL=" "$env_file" 2>/dev/null; then
        local server_url
        server_url=$(grep "^REACT_APP_SERVER_URL=" "$env_file" | cut -d'=' -f2-)

        if [[ -n "$server_url" ]] && ! grep -q "^REACT_APP_MDS_SERVER_URL=" "$env_file" 2>/dev/null; then
            printf '\nREACT_APP_MDS_SERVER_URL=%s\n' "$server_url" >> "$env_file"
            log_warn "Migrated obsolete REACT_APP_SERVER_URL to REACT_APP_MDS_SERVER_URL"
        fi
        sed -i '/^REACT_APP_SERVER_URL=.*/d;/^# REACT_APP_SERVER_URL=.*/d' "$env_file"
        log_info "Removed obsolete REACT_APP_SERVER_URL from dashboard .env"
        return 0
    fi

    sed -i '/^# REACT_APP_SERVER_URL=.*/d' "$env_file"
    log_info "Dashboard env cleanup complete"

    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_env_config_phase() {
    print_phase_header "8" "Environment Configuration" "9"

    # Check skip flag
    if [[ "${SKIP_ENV_CONFIG:-false}" == "true" ]]; then
        log_info "Skipping environment configuration (--skip-env-config)"
        return 0
    fi

    print_section "Dashboard Configuration"
    configure_dashboard_env || return 1

    print_section "System Configuration"
    configure_gcs_env || return 1

    print_section "Dashboard Env Cleanup"
    cleanup_dashboard_env || return 1

    echo ""
    log_success "Environment configuration phase completed"
    return 0
}
