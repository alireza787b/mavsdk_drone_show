#!/bin/bash
# =============================================================================
# MDS Initialization Library: Repository Operations
# =============================================================================
# Version: 4.5.0
# Description: Git repository cloning, updating, and SSH key management
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_REPO_LOADED:-}" ]] && return 0
_MDS_REPO_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly DEFAULT_REPO_URL="git@github.com:alireza787b/mavsdk_drone_show.git"
readonly DEFAULT_REPO_URL_HTTPS="https://github.com/alireza787b/mavsdk_drone_show.git"
readonly DEFAULT_BRANCH="main-candidate"
readonly SSH_KEY_PATH="/home/${MDS_USER}/.ssh/id_rsa_git_deploy"

mds_git_ssh_command() {
    printf 'ssh -i %q -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' "$SSH_KEY_PATH"
}

is_github_ssh_repo_url() {
    [[ "${1:-}" == git@github.com:* ]]
}

prepare_repo_ssh_runtime() {
    local ssh_dir="/home/${MDS_USER}/.ssh"

    mkdir -p "$ssh_dir"
    chown "${MDS_USER}:${MDS_USER}" "$ssh_dir"
    chmod 700 "$ssh_dir"

    if [[ -f "$SSH_KEY_PATH" ]]; then
        chmod 600 "$SSH_KEY_PATH"
        chown "${MDS_USER}:${MDS_USER}" "$SSH_KEY_PATH"
    fi

    if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
        chmod 644 "${SSH_KEY_PATH}.pub"
        chown "${MDS_USER}:${MDS_USER}" "${SSH_KEY_PATH}.pub"
    fi

    sudo -u "${MDS_USER}" bash -lc 'if ! grep -q "github.com" "$HOME/.ssh/known_hosts" 2>/dev/null; then ssh-keyscan -t ed25519 github.com >> "$HOME/.ssh/known_hosts" 2>/dev/null || true; fi'
}

configure_repo_ssh_command() {
    local repo_url="$1"

    if ! repo_exists; then
        return 0
    fi

    if is_github_ssh_repo_url "$repo_url"; then
        sudo -u "${MDS_USER}" git -C "${MDS_INSTALL_DIR}" config core.sshCommand "$(mds_git_ssh_command)"
    else
        sudo -u "${MDS_USER}" git -C "${MDS_INSTALL_DIR}" config --unset-all core.sshCommand >/dev/null 2>&1 || true
    fi
}

# =============================================================================
# SSH KEY MANAGEMENT
# =============================================================================

# Check if SSH key exists
ssh_key_exists() {
    [[ -f "${SSH_KEY_PATH}" ]]
}

# Generate SSH deploy key
generate_ssh_key() {
    log_step "Generating SSH deploy key..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would generate SSH key at: ${SSH_KEY_PATH}${NC}"
        return 0
    fi

    local ssh_dir="/home/${MDS_USER}/.ssh"

    # Create .ssh directory if needed
    if [[ ! -d "$ssh_dir" ]]; then
        mkdir -p "$ssh_dir"
        chown "${MDS_USER}:${MDS_USER}" "$ssh_dir"
        chmod 700 "$ssh_dir"
    fi

    # Generate key if it doesn't exist
    if ssh_key_exists; then
        log_info "SSH key already exists at: ${SSH_KEY_PATH}"
        return 0
    fi

    # Generate new SSH key
    sudo -u "${MDS_USER}" ssh-keygen -t rsa -b 4096 \
        -f "${SSH_KEY_PATH}" \
        -N "" \
        -C "mds-drone-deploy-$(hostname)" || {
        log_error "Failed to generate SSH key"
        return 1
    }

    chmod 600 "${SSH_KEY_PATH}"
    chmod 644 "${SSH_KEY_PATH}.pub"
    chown "${MDS_USER}:${MDS_USER}" "${SSH_KEY_PATH}" "${SSH_KEY_PATH}.pub"

    log_success "SSH key generated: ${SSH_KEY_PATH}"
    return 0
}

# Configure SSH for GitHub
configure_ssh_for_github() {
    log_step "Configuring SSH for GitHub..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would configure SSH for GitHub${NC}"
        return 0
    fi

    prepare_repo_ssh_runtime
    log_success "SSH GitHub access prepared"
    return 0
}

# Display deploy key instructions
display_deploy_key_instructions() {
    local repo_url="${1:-$DEFAULT_REPO_URL}"

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}GitHub Deploy Key Setup${NC}                                                  ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}1. Copy the public key below:${NC}                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""

    # Display the public key
    if [[ -f "${SSH_KEY_PATH}.pub" ]]; then
        echo -e "${GREEN}"
        cat "${SSH_KEY_PATH}.pub"
        echo -e "${NC}"
    else
        echo -e "${YELLOW}  [Public key not found]${NC}"
    fi

    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}2. Add to GitHub:${NC}                                                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     • Go to your repository: ${DIM}${repo_url}${NC}                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     • Navigate to: Settings → Deploy Keys → Add Deploy Key              ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     • Title: ${GREEN}mds-drone-$(hostname)${NC}                                        ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     • Key: Paste the public key above                                   ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     • ${YELLOW}Enable \"Allow write access\" for git sync functionality${NC}            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${BOLD}3. Verify connection:${NC}                                                    ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}     ${GREEN}ssh -i ${SSH_KEY_PATH} -o IdentitiesOnly=yes -T git@github.com${NC}      ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Test SSH connection to GitHub
test_ssh_connection() {
    log_step "Testing SSH connection to GitHub..."

    # Test connection (suppress expected "You've successfully authenticated" message)
    local output
    prepare_repo_ssh_runtime
    output=$(sudo -u "${MDS_USER}" ssh -T -o StrictHostKeyChecking=accept-new \
        -o BatchMode=yes -o ConnectTimeout=10 \
        -o IdentitiesOnly=yes \
        -i "${SSH_KEY_PATH}" git@github.com 2>&1) || true

    if echo "$output" | grep -q "successfully authenticated"; then
        log_success "SSH connection to GitHub verified"
        return 0
    elif echo "$output" | grep -q "Permission denied"; then
        log_warn "SSH key not authorized - deploy key may need to be added to GitHub"
        return 1
    else
        log_warn "SSH connection test inconclusive: $output"
        return 1
    fi
}

# =============================================================================
# FORK SELECTION
# =============================================================================

# Normalize a GitHub owner or owner/repo shorthand into an owner/repo path
normalize_github_repo_path() {
    local spec="${1:-}"

    spec="${spec#https://github.com/}"
    spec="${spec#git@github.com:}"
    spec="${spec#github.com/}"
    spec="${spec%.git}"
    spec="${spec#/}"

    if [[ -z "$spec" ]]; then
        return 1
    fi

    if [[ "$spec" != */* ]]; then
        spec="${spec}/mavsdk_drone_show"
    fi

    printf '%s\n' "$spec"
}

# Display repository selection prompt
display_repo_selection_box() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${WHITE}Repository Selection${NC}                                                      ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Do you have your own fork or custom GitHub repository for MDS?            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[1]${NC} No - Use default repository ${DIM}(read-only unless you're a collaborator)${NC}  ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}    ${GREEN}[2]${NC} Yes - I have my own repo ${DIM}(recommended for production)${NC}           ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Display read-only warning for default repo
display_readonly_warning() {
    echo ""
    echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│${NC}  ${YELLOW}Note: Read-Only Access${NC}                                                    ${CYAN}│${NC}"
    echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  Using the default repository in read-only mode.                          ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${DIM}• git_sync_mds service will pull updates automatically${NC}                  ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${DIM}• You cannot push local changes unless you're a collaborator${NC}            ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}  ${DIM}• For custom modifications, use your own fork or org repo${NC}               ${CYAN}│${NC}"
    echo -e "${CYAN}│${NC}                                                                            ${CYAN}│${NC}"
    echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Prompt for custom GitHub owner / repo path
prompt_custom_repo_path() {
    local repo_spec=""
    local repo_path=""

    echo ""
    echo -e "  ${INFO} Enter your GitHub owner or owner/repo path."
    echo -e "  ${DIM}Examples: youruser   or   yourorg/customer-mds${NC}"
    echo ""
    prompt_input "GitHub owner or owner/repo" "" repo_spec

    if [[ -z "$repo_spec" ]]; then
        log_warn "No repository provided, using default repository"
        return 1
    fi

    repo_path=$(normalize_github_repo_path "$repo_spec") || {
        log_warn "Invalid repository selection, using default repository"
        return 1
    }

    # Set the repository URL based on access method preference
    if [[ "${USE_HTTPS:-false}" == "true" ]]; then
        REPO_URL="https://github.com/${repo_path}.git"
    else
        REPO_URL="git@github.com:${repo_path}.git"
    fi

    log_info "Using custom repository: ${repo_path}"
    return 0
}

# Interactive repository selection
prompt_repository_selection() {
    # If REPO_URL already set (from CLI), skip prompt
    if [[ -n "${REPO_URL:-}" ]]; then
        log_info "Repository URL provided via CLI: ${REPO_URL}"
        return 0
    fi

    # Non-interactive mode: use default
    if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
        REPO_URL="${DEFAULT_REPO_URL_HTTPS}"
        USE_HTTPS="true"
        log_info "Non-interactive mode: using default repository (HTTPS)"
        return 0
    fi

    # Interactive selection
    display_repo_selection_box

    local choice=""
    prompt_input "Select option (1 or 2)" "1" choice

    case "$choice" in
        1)
            # Default repo - use HTTPS for read-only
            REPO_URL="${DEFAULT_REPO_URL_HTTPS}"
            USE_HTTPS="true"
            display_readonly_warning
            ;;
        2)
            # Custom repo - prompt for owner / repo path
            if ! prompt_custom_repo_path; then
                # Fallback to default if no username provided
                REPO_URL="${DEFAULT_REPO_URL_HTTPS}"
                USE_HTTPS="true"
                display_readonly_warning
            fi
            ;;
        *)
            log_warn "Invalid selection, using default repository"
            REPO_URL="${DEFAULT_REPO_URL_HTTPS}"
            USE_HTTPS="true"
            display_readonly_warning
            ;;
    esac

    return 0
}

# =============================================================================
# GIT ACCESS METHODS
# =============================================================================

# Detect preferred git access method
detect_git_access_method() {
    local repo_url="${1:-}"

    # If URL explicitly starts with https, use HTTPS
    if [[ "$repo_url" == https://* ]]; then
        echo "https"
        return 0
    fi

    # If URL explicitly starts with git@, use SSH
    if [[ "$repo_url" == git@* ]]; then
        echo "ssh"
        return 0
    fi

    # If USE_HTTPS is set, prefer HTTPS
    if [[ "${USE_HTTPS:-false}" == "true" ]]; then
        echo "https"
        return 0
    fi

    # Default to SSH
    echo "ssh"
}

# Convert URL to appropriate format
convert_repo_url() {
    local url="$1"
    local target_method="$2"

    # Already in target format
    if [[ "$target_method" == "ssh" && "$url" == git@* ]]; then
        echo "$url"
        return 0
    fi

    if [[ "$target_method" == "https" && "$url" == https://* ]]; then
        echo "$url"
        return 0
    fi

    # Convert HTTPS to SSH
    if [[ "$target_method" == "ssh" && "$url" == https://* ]]; then
        echo "$url" | sed 's|https://github.com/|git@github.com:|'
        return 0
    fi

    # Convert SSH to HTTPS
    if [[ "$target_method" == "https" && "$url" == git@* ]]; then
        echo "$url" | sed 's|git@github.com:|https://github.com/|'
        return 0
    fi

    # Return as-is if no conversion needed
    echo "$url"
}

is_github_https_repo_url() {
    [[ "${1:-}" == https://github.com/* ]]
}

node_git_auth_enabled() {
    [[ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" && -r "${MDS_GIT_AUTH_TOKEN_FILE}" ]] || [[ -n "${MDS_GIT_AUTH_TOKEN:-}" ]]
}

node_git_askpass_path() {
    printf '%s\n' "/tmp/mds_node_git_askpass_runtime.sh"
}

prepare_node_git_askpass() {
    local askpass_path
    askpass_path="$(node_git_askpass_path)"

    if [[ -x "$askpass_path" ]]; then
        return 0
    fi

    cat >"$askpass_path" <<'EOF'
#!/bin/sh
prompt="${1:-}"
if printf '%s' "$prompt" | grep -qi 'username'; then
    printf '%s\n' "${MDS_GIT_AUTH_USERNAME:-x-access-token}"
    exit 0
fi
if [ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" ] && [ -r "${MDS_GIT_AUTH_TOKEN_FILE}" ]; then
    tr -d '\r\n' < "${MDS_GIT_AUTH_TOKEN_FILE}"
    exit 0
fi
printf '%s\n' "${MDS_GIT_AUTH_TOKEN:-}"
EOF

    chmod 700 "$askpass_path"
}

run_git_as_mds_user_for_repo() {
    local repo_url="$1"
    shift

    if [[ "${repo_url}" == git@* ]]; then
        sudo -u "${MDS_USER}" env GIT_SSH_COMMAND="$(mds_git_ssh_command)" git "$@"
    elif is_github_https_repo_url "$repo_url" && node_git_auth_enabled; then
        prepare_node_git_askpass
        sudo -u "${MDS_USER}" env \
            GIT_TERMINAL_PROMPT=0 \
            GIT_ASKPASS_REQUIRE=force \
            GIT_ASKPASS="$(node_git_askpass_path)" \
            MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}" \
            MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
            MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
            git -c credential.username="${MDS_GIT_AUTH_USERNAME:-x-access-token}" "$@"
    else
        sudo -u "${MDS_USER}" git "$@"
    fi
}

# =============================================================================
# REPOSITORY OPERATIONS
# =============================================================================

# Check if repository exists
repo_exists() {
    [[ -d "${MDS_INSTALL_DIR}/.git" ]]
}

# Clone the repository
clone_repository() {
    local repo_url="${1:-$DEFAULT_REPO_URL}"
    local branch="${2:-$DEFAULT_BRANCH}"
    local access_method="${3:-ssh}"

    log_step "Cloning repository..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would clone: ${repo_url} (branch: ${branch})${NC}"
        return 0
    fi

    # Convert URL to appropriate format
    repo_url=$(convert_repo_url "$repo_url" "$access_method")

    log_info "Repository: $repo_url"
    log_info "Branch: $branch"
    log_info "Target: ${MDS_INSTALL_DIR}"

    # Create parent directory if needed
    local parent_dir
    parent_dir=$(dirname "${MDS_INSTALL_DIR}")
    mkdir -p "$parent_dir"
    chown "${MDS_USER}:${MDS_USER}" "$parent_dir"

    local clone_try=1
    local clone_ok="false"
    while [[ $clone_try -le 3 ]]; do
        if run_git_as_mds_user_for_repo "$repo_url" clone --branch "$branch" "$repo_url" "${MDS_INSTALL_DIR}"; then
            clone_ok="true"
            break
        fi
        sleep $((clone_try * 5))
        clone_try=$((clone_try + 1))
    done

    if [[ "$clone_ok" == "true" ]]; then
        configure_repo_ssh_command "$repo_url"
        log_success "Repository cloned successfully"
        state_set_value "repo_url" "$repo_url"
        state_set_value "repo_branch" "$branch"
        return 0
    fi

    log_error "Failed to clone repository"
    return 1
}

# Update existing repository
update_repository() {
    local branch="${1:-$DEFAULT_BRANCH}"

    log_step "Updating repository..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would update repository to branch: ${branch}${NC}"
        return 0
    fi

    cd "${MDS_INSTALL_DIR}" || return 1
    local current_remote
    current_remote=$(sudo -u "${MDS_USER}" git -C "${MDS_INSTALL_DIR}" remote get-url origin 2>/dev/null || echo "")
    configure_repo_ssh_command "$current_remote"

    # Fetch latest
    log_info "Fetching latest changes..."
    if ! run_git_as_mds_user_for_repo "$current_remote" -C "${MDS_INSTALL_DIR}" fetch --all --prune; then
        log_warn "Failed to fetch, attempting repair..."
        sudo -u "${MDS_USER}" git-repair 2>/dev/null || true
        run_git_as_mds_user_for_repo "$current_remote" -C "${MDS_INSTALL_DIR}" fetch --all --prune || {
            log_error "Failed to fetch after repair"
            return 1
        }
    fi

    # Checkout branch
    log_info "Checking out branch: $branch"
    run_git_as_mds_user_for_repo "$current_remote" -C "${MDS_INSTALL_DIR}" checkout "$branch" 2>/dev/null || \
        run_git_as_mds_user_for_repo "$current_remote" -C "${MDS_INSTALL_DIR}" checkout -b "$branch" "origin/$branch" || {
        log_error "Failed to checkout branch: $branch"
        return 1
    }

    # Reset to origin
    log_info "Synchronizing with remote..."
    run_git_as_mds_user_for_repo "$current_remote" -C "${MDS_INSTALL_DIR}" reset --hard "origin/$branch" || {
        log_error "Failed to reset to origin/$branch"
        return 1
    }

    # Get current commit
    local commit
    commit=$(sudo -u "${MDS_USER}" git rev-parse --short HEAD)
    state_set_value "repo_commit" "$commit"

    log_success "Repository updated to commit: $commit"
    return 0
}

# Validate repository structure
validate_repo_structure() {
    log_step "Validating repository structure..."

    local required_files=(
        "coordinator.py"
        "src/params.py"
        "requirements.txt"
        "led_indicator.py"
    )

    local missing=()

    for file in "${required_files[@]}"; do
        if [[ ! -f "${MDS_INSTALL_DIR}/${file}" ]]; then
            missing+=("$file")
        fi
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        log_error "Missing required files: ${missing[*]}"
        return 1
    fi

    log_success "Repository structure validated"
    return 0
}

# Check if params.py matches fork configuration
verify_fork_config() {
    local expected_url="${1:-}"
    local expected_branch="${2:-}"

    if [[ -z "$expected_url" && -z "$expected_branch" ]]; then
        return 0  # No fork config to verify
    fi

    log_step "Verifying fork configuration..."

    local params_file="${MDS_INSTALL_DIR}/src/params.py"

    if [[ ! -f "$params_file" ]]; then
        log_warn "Cannot verify fork config - params.py not found"
        return 0
    fi

    local config_url config_branch
    config_url=$(grep -oP "GIT_REPO_URL\s*=.*?['\"]([^'\"]+)['\"]" "$params_file" 2>/dev/null | grep -oP "['\"][^'\"]+['\"]" | tr -d "'\"" || echo "")
    config_branch=$(grep -oP "GIT_BRANCH\s*=.*?['\"]([^'\"]+)['\"]" "$params_file" 2>/dev/null | grep -oP "['\"][^'\"]+['\"]" | tr -d "'\"" || echo "")

    local mismatch=false

    if [[ -n "$expected_url" && "$config_url" != *"$expected_url"* ]]; then
        log_warn "params.py GIT_REPO_URL ($config_url) differs from specified ($expected_url)"
        mismatch=true
    fi

    if [[ -n "$expected_branch" && "$config_branch" != "$expected_branch" ]]; then
        log_warn "params.py GIT_BRANCH ($config_branch) differs from specified ($expected_branch)"
        mismatch=true
    fi

    if [[ "$mismatch" == "true" ]]; then
        echo ""
        echo -e "  ${YELLOW}Note: Environment variables (MDS_REPO_URL, MDS_BRANCH) will override${NC}"
        echo -e "  ${YELLOW}params.py settings at runtime via /etc/mds/local.env${NC}"
        echo ""
    else
        log_success "Fork configuration matches"
    fi

    return 0
}

# =============================================================================
# MAIN REPOSITORY RUNNER
# =============================================================================

run_repository_phase() {
    local branch="${BRANCH:-$DEFAULT_BRANCH}"
    local access_method

    print_phase_header "3" "Repository Setup"

    set_led_state "GIT_SYNCING"

    print_section "Repository Selection"

    # Interactive fork selection (skipped if REPO_URL already set via CLI)
    prompt_repository_selection

    # Now use the selected/configured repo URL
    local repo_url="${REPO_URL:-$DEFAULT_REPO_URL}"

    # Determine access method
    access_method=$(detect_git_access_method "$repo_url")
    log_info "Git access method: $access_method"
    log_info "Repository: $repo_url"

    # SSH setup if using SSH
    if [[ "$access_method" == "ssh" ]]; then
        print_section "SSH Key Setup"

        if ! ssh_key_exists; then
            generate_ssh_key || return 1
            configure_ssh_for_github || return 1

            # Display instructions and test connection
            display_deploy_key_instructions "$repo_url"

            # In non-interactive mode, we can't wait for key to be added to GitHub
            if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
                log_error "Non-interactive mode: SSH key was just generated but not yet authorized on GitHub"
                log_info "Options:"
                log_info "  1. Add the deploy key to GitHub, then run this script again"
                log_info "  2. Use --https flag for HTTPS-based cloning (no SSH key needed)"
                return 1
            fi

            echo ""
            echo -e "  ${INFO} Add the deploy key to GitHub before continuing."
            echo ""

            if ! confirm "Have you added the deploy key to GitHub?" "n"; then
                log_warn "Cannot proceed without deploy key authorization"
                log_info "Run this script again after adding the deploy key"
                return 1
            fi
        else
            log_info "SSH key already exists"
            configure_ssh_for_github || return 1
        fi

        # Test SSH connection
        if ! test_ssh_connection; then
            log_warn "SSH connection test failed"

            if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
                # In non-interactive mode, SSH must work or we fail
                log_error "Non-interactive mode: SSH authentication failed"
                log_info "Options:"
                log_info "  1. Ensure the deploy key is added to GitHub, then run again"
                log_info "  2. Use --https flag for HTTPS-based cloning"
                return 1
            fi

            display_deploy_key_instructions "$repo_url"

            if ! confirm "Retry SSH connection test?" "y"; then
                if confirm "Switch to HTTPS access instead?" "y"; then
                    access_method="https"
                    repo_url=$(convert_repo_url "$repo_url" "https")
                else
                    return 1
                fi
            elif ! test_ssh_connection; then
                log_error "SSH connection still failing"
                return 1
            fi
        fi
    fi

    # Clone or update repository
    print_section "Repository Operations"

    if repo_exists; then
        log_info "Repository exists, updating..."
        update_repository "$branch" || return 1
    else
        log_info "Cloning repository..."
        clone_repository "$repo_url" "$branch" "$access_method" || return 1
    fi

    # Validate structure
    validate_repo_structure || return 1

    # Verify fork config if using custom repo
    if [[ "$repo_url" != "$DEFAULT_REPO_URL" && "$repo_url" != "$DEFAULT_REPO_URL_HTTPS" ]]; then
        verify_fork_config "$repo_url" "$branch"
    fi

    set_led_state "GIT_SUCCESS"
    log_success "Repository setup complete"
    return 0
}
