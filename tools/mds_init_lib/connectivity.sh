#!/bin/bash
# =============================================================================
# MDS Initialization Library: Optional Connectivity Backends
# =============================================================================
# Version: 4.5.0
# Description: Optional connectivity-service integration (smart-wifi-manager)
# =============================================================================

[[ -n "${_MDS_CONNECTIVITY_LOADED:-}" ]] && return 0
_MDS_CONNECTIVITY_LOADED=1

SMART_WIFI_MANAGER_REPO_URL_EXPLICIT="false"
SMART_WIFI_MANAGER_REF_EXPLICIT="false"
[[ -n "${MDS_SMART_WIFI_MANAGER_REPO_URL+x}" ]] && SMART_WIFI_MANAGER_REPO_URL_EXPLICIT="true"
[[ -n "${MDS_SMART_WIFI_MANAGER_REF+x}" ]] && SMART_WIFI_MANAGER_REF_EXPLICIT="true"

MDS_CONNECTIVITY_BACKEND="${MDS_CONNECTIVITY_BACKEND:-${MDS_DEFAULT_CONNECTIVITY_BACKEND:-none}}"
SMART_WIFI_MANAGER_MODE="${MDS_SMART_WIFI_MANAGER_MODE:-${MDS_DEFAULT_SMART_WIFI_MANAGER_MODE:-observe}}"
SMART_WIFI_MANAGER_IMPORT_MODE="${MDS_SMART_WIFI_MANAGER_IMPORT_MODE:-${MDS_DEFAULT_SMART_WIFI_MANAGER_IMPORT_MODE:-replace}}"
SMART_WIFI_MANAGER_REPO_URL="${MDS_SMART_WIFI_MANAGER_REPO_URL:-${MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS:-https://github.com/${MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_SLUG:-alireza787b/smart-wifi-manager}.git}}"
SMART_WIFI_MANAGER_REF="${MDS_SMART_WIFI_MANAGER_REF:-${MDS_DEFAULT_SMART_WIFI_MANAGER_REF:-v2.1.0}}"
SMART_WIFI_MANAGER_INSTALL_DIR="${MDS_SMART_WIFI_MANAGER_INSTALL_DIR:-${MDS_DEFAULT_SMART_WIFI_MANAGER_INSTALL_DIR:-/opt/smart-wifi-manager}}"
SMART_WIFI_MANAGER_DASHBOARD_LISTEN="${MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-${MDS_DEFAULT_SMART_WIFI_MANAGER_DASHBOARD_LISTEN:-127.0.0.1:9080}}"
SMART_WIFI_MANAGER_PROFILE_SOURCE="${MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE:-}"
SMART_WIFI_MANAGER_CONFIG_FILE="${MDS_SMART_WIFI_MANAGER_CONFIG_FILE:-}"
SMART_WIFI_MANAGER_SKIP_DASHBOARD="${MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD:-false}"
CONNECTIVITY_SELECTION_EXPLICIT="${CONNECTIVITY_SELECTION_EXPLICIT:-false}"

readonly SMART_WIFI_MANAGER_SERVICE="smart-wifi-manager.service"
readonly SMART_WIFI_MANAGER_DEFAULT_PROFILE_RELATIVE="${MDS_DEFAULT_SMART_WIFI_MANAGER_PROFILE_PATH:-deployment/connectivity/smart-wifi-manager/profile.json}"

normalize_connectivity_backend() {
    case "${1:-none}" in
        none|manual)
            printf 'none\n'
            ;;
        smart-wifi-manager|smart_wifi_manager|smartwifi|wifi)
            printf 'smart-wifi-manager\n'
            ;;
        *)
            return 1
            ;;
    esac
}

normalize_smart_wifi_mode() {
    case "${1:-observe}" in
        manage|observe|disabled)
            printf '%s\n' "$1"
            ;;
        *)
            return 1
            ;;
    esac
}

normalize_smart_wifi_import_mode() {
    case "${1:-replace}" in
        replace|merge)
            printf '%s\n' "$1"
            ;;
        *)
            return 1
            ;;
    esac
}

smart_wifi_default_profile_path() {
    printf '%s\n' "${MDS_INSTALL_DIR}/${SMART_WIFI_MANAGER_DEFAULT_PROFILE_RELATIVE}"
}

smart_wifi_default_profile_exists() {
    [[ -f "$(smart_wifi_default_profile_path)" ]]
}

resolve_smart_wifi_profile_source_path() {
    local profile_source="${SMART_WIFI_MANAGER_PROFILE_SOURCE:-}"

    if [[ -z "$profile_source" ]] && smart_wifi_default_profile_exists; then
        profile_source="repo:${SMART_WIFI_MANAGER_DEFAULT_PROFILE_RELATIVE}"
    fi

    case "$profile_source" in
        repo:*)
            printf '%s\n' "${MDS_INSTALL_DIR}/${profile_source#repo:}"
            ;;
        file:*)
            printf '%s\n' "${profile_source#file:}"
            ;;
        /*)
            printf '%s\n' "$profile_source"
            ;;
        "")
            printf '\n'
            ;;
        *)
            printf '%s\n' "$profile_source"
            ;;
    esac
}

prompt_connectivity_backend() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}Connectivity Backend${NC}                                                      ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}  Choose how this node should manage network connectivity at runtime.         ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Core MDS services no longer depend on a built-in Wi-Fi manager.            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[1]${NC} No connectivity manager (manual / Ethernet / modem / VPN)        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[2]${NC} Install Smart Wi-Fi Manager in observe mode                       ${CYAN}│${NC}"
    if smart_wifi_default_profile_exists; then
        echo -e "${CYAN}│${NC}    ${GREEN}[3]${NC} Install Smart Wi-Fi Manager and import repo profile               ${CYAN}│${NC}"
    else
        echo -e "${CYAN}│${NC}    ${DIM}[3] Repo Wi-Fi profile not present in this checkout${NC}                    ${CYAN}│${NC}"
    fi
    echo -e "${CYAN}│${NC}    ${GREEN}[4]${NC} Install Smart Wi-Fi Manager and import a local JSON file         ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""

    local choice=""
    prompt_input "Select option (1-4)" "1" choice

    case "$choice" in
        1)
            MDS_CONNECTIVITY_BACKEND="none"
            SMART_WIFI_MANAGER_PROFILE_SOURCE=""
            SMART_WIFI_MANAGER_CONFIG_FILE=""
            ;;
        2)
            MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
            SMART_WIFI_MANAGER_MODE="observe"
            SMART_WIFI_MANAGER_PROFILE_SOURCE=""
            SMART_WIFI_MANAGER_CONFIG_FILE=""
            ;;
        3)
            if ! smart_wifi_default_profile_exists; then
                log_warn "No repo-managed Smart Wi-Fi Manager profile is present"
                return 1
            fi
            MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
            SMART_WIFI_MANAGER_MODE="manage"
            SMART_WIFI_MANAGER_PROFILE_SOURCE="repo:${SMART_WIFI_MANAGER_DEFAULT_PROFILE_RELATIVE}"
            SMART_WIFI_MANAGER_CONFIG_FILE=""
            ;;
        4)
            local config_path=""
            prompt_input "Enter Smart Wi-Fi Manager JSON file path" "" config_path
            if [[ -z "$config_path" ]]; then
                log_warn "No config path provided"
                return 1
            fi
            MDS_CONNECTIVITY_BACKEND="smart-wifi-manager"
            SMART_WIFI_MANAGER_MODE="manage"
            SMART_WIFI_MANAGER_PROFILE_SOURCE="file:${config_path}"
            SMART_WIFI_MANAGER_CONFIG_FILE="$config_path"
            ;;
        *)
            log_warn "Unsupported selection: ${choice}"
            return 1
            ;;
    esac

    CONNECTIVITY_SELECTION_EXPLICIT="true"
    export MDS_CONNECTIVITY_BACKEND SMART_WIFI_MANAGER_MODE SMART_WIFI_MANAGER_PROFILE_SOURCE
    export SMART_WIFI_MANAGER_CONFIG_FILE CONNECTIVITY_SELECTION_EXPLICIT
    return 0
}

persist_connectivity_local_env() {
    update_local_env_value "MDS_CONNECTIVITY_BACKEND" "${MDS_CONNECTIVITY_BACKEND}"

    if [[ "${MDS_CONNECTIVITY_BACKEND}" != "smart-wifi-manager" ]]; then
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_MODE"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_IMPORT_MODE"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_REPO_URL"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_REF"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_INSTALL_DIR"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_CONFIG_FILE"
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD"
        return 0
    fi

    update_local_env_value "MDS_SMART_WIFI_MANAGER_MODE" "${SMART_WIFI_MANAGER_MODE}"
    update_local_env_value "MDS_SMART_WIFI_MANAGER_IMPORT_MODE" "${SMART_WIFI_MANAGER_IMPORT_MODE}"
    if [[ "${SMART_WIFI_MANAGER_REPO_URL_EXPLICIT}" == "true" ]]; then
        update_local_env_value "MDS_SMART_WIFI_MANAGER_REPO_URL" "${SMART_WIFI_MANAGER_REPO_URL}"
    else
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_REPO_URL"
    fi
    if [[ "${SMART_WIFI_MANAGER_REF_EXPLICIT}" == "true" ]]; then
        update_local_env_value "MDS_SMART_WIFI_MANAGER_REF" "${SMART_WIFI_MANAGER_REF}"
    else
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_REF"
    fi
    update_local_env_value "MDS_SMART_WIFI_MANAGER_INSTALL_DIR" "${SMART_WIFI_MANAGER_INSTALL_DIR}"
    update_local_env_value "MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN" "${SMART_WIFI_MANAGER_DASHBOARD_LISTEN}"
    update_local_env_value "MDS_SMART_WIFI_MANAGER_SKIP_DASHBOARD" "${SMART_WIFI_MANAGER_SKIP_DASHBOARD}"

    if [[ -n "${SMART_WIFI_MANAGER_PROFILE_SOURCE:-}" ]]; then
        update_local_env_value "MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE" "${SMART_WIFI_MANAGER_PROFILE_SOURCE}"
    else
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_PROFILE_SOURCE"
    fi

    if [[ -n "${SMART_WIFI_MANAGER_CONFIG_FILE:-}" ]]; then
        update_local_env_value "MDS_SMART_WIFI_MANAGER_CONFIG_FILE" "${SMART_WIFI_MANAGER_CONFIG_FILE}"
    else
        remove_local_env_value "MDS_SMART_WIFI_MANAGER_CONFIG_FILE"
    fi
}

run_connectivity_reconcile() {
    local reconcile_script="${MDS_INSTALL_DIR}/tools/reconcile_connectivity.sh"

    if [[ ! -x "${reconcile_script}" ]]; then
        log_warn "Connectivity reconcile helper not found: ${reconcile_script}"
        return 1
    fi

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would run: ${reconcile_script} apply --force${NC}"
        return 0
    fi

    "${reconcile_script}" apply --force
}

run_connectivity_phase() {
    print_phase_header "13" "Connectivity Backend"

    if [[ "${NON_INTERACTIVE:-false}" != "true" && "${CONNECTIVITY_SELECTION_EXPLICIT}" != "true" ]]; then
        prompt_connectivity_backend || true
    fi

    if ! MDS_CONNECTIVITY_BACKEND="$(normalize_connectivity_backend "${MDS_CONNECTIVITY_BACKEND}")"; then
        log_error "Unsupported connectivity backend: ${MDS_CONNECTIVITY_BACKEND}"
        return 1
    fi
    export MDS_CONNECTIVITY_BACKEND

    if [[ "${MDS_CONNECTIVITY_BACKEND}" == "none" ]]; then
        log_info "Connectivity backend: none"
        persist_connectivity_local_env
        state_set_value "connectivity_backend" "none"
        log_success "Manual/host-managed networking selected"
        return 0
    fi

    if ! SMART_WIFI_MANAGER_MODE="$(normalize_smart_wifi_mode "${SMART_WIFI_MANAGER_MODE}")"; then
        log_error "Unsupported Smart Wi-Fi Manager mode: ${SMART_WIFI_MANAGER_MODE}"
        return 1
    fi
    if ! SMART_WIFI_MANAGER_IMPORT_MODE="$(normalize_smart_wifi_import_mode "${SMART_WIFI_MANAGER_IMPORT_MODE}")"; then
        log_error "Unsupported Smart Wi-Fi Manager import mode: ${SMART_WIFI_MANAGER_IMPORT_MODE}"
        return 1
    fi
    export SMART_WIFI_MANAGER_MODE SMART_WIFI_MANAGER_IMPORT_MODE

    print_section "Connectivity Runtime Configuration"
    persist_connectivity_local_env || return 1
    run_connectivity_reconcile || return 1

    state_set_value "connectivity_backend" "smart-wifi-manager"
    state_set_value "connectivity_backend_mode" "${SMART_WIFI_MANAGER_MODE}"
    log_success "Smart Wi-Fi Manager configured"
    return 0
}
