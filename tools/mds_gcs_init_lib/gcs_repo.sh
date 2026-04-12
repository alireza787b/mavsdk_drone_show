#!/bin/bash
# =============================================================================
# MDS GCS Initialization Library: Repository Setup
# =============================================================================
# Version: 4.4.0
# Description: Clone/update repository with SSH key management for WRITE access
# Author: MDS Team
# =============================================================================

# Prevent double-sourcing
[[ -n "${_MDS_GCS_REPO_LOADED:-}" ]] && return 0
_MDS_GCS_REPO_LOADED=1

# =============================================================================
# CONSTANTS
# =============================================================================

readonly GCS_SSH_KEY_PATH="${HOME}/.ssh/mds_gcs_deploy_key"
readonly GCS_SSH_KEY_PUB="${GCS_SSH_KEY_PATH}.pub"

gcs_git_ssh_command() {
    printf 'ssh -i %q -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new' "$GCS_SSH_KEY_PATH"
}

is_github_ssh_repo_url() {
    [[ "${1:-}" == git@github.com:* ]]
}

prepare_gcs_ssh_runtime() {
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"

    if [[ -f "$GCS_SSH_KEY_PATH" ]]; then
        chmod 600 "$GCS_SSH_KEY_PATH"
    fi

    if [[ -f "$GCS_SSH_KEY_PUB" ]]; then
        chmod 644 "$GCS_SSH_KEY_PUB"
    fi

    if ! grep -q "github.com" "${HOME}/.ssh/known_hosts" 2>/dev/null; then
        ssh-keyscan -t ed25519 github.com >> "${HOME}/.ssh/known_hosts" 2>/dev/null || true
    fi
}

configure_repo_ssh_command() {
    local repo_dir="$1"
    local repo_url="$2"

    if ! [[ -d "${repo_dir}/.git" ]]; then
        return 0
    fi

    if is_github_ssh_repo_url "$repo_url"; then
        git -C "$repo_dir" config core.sshCommand "$(gcs_git_ssh_command)"
    else
        git -C "$repo_dir" config --unset-all core.sshCommand >/dev/null 2>&1 || true
    fi
}

is_github_https_repo_url() {
    [[ "${1:-}" == https://github.com/* ]]
}

gcs_should_use_https_access() {
    local repo_url="${1:-${REPO_URL:-}}"

    if is_github_ssh_repo_url "$repo_url"; then
        return 1
    fi

    if [[ "${USE_HTTPS:-false}" == "true" ]]; then
        return 0
    fi

    if is_github_https_repo_url "$repo_url"; then
        return 0
    fi

    if gcs_git_auth_enabled; then
        return 0
    fi

    return 1
}

gcs_git_auth_enabled() {
    [[ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" && -r "${MDS_GIT_AUTH_TOKEN_FILE}" ]] || [[ -n "${MDS_GIT_AUTH_TOKEN:-}" ]]
}

gcs_git_askpass_path() {
    printf '%s\n' "/tmp/mds_gcs_git_askpass_runtime.sh"
}

prepare_gcs_git_askpass() {
    local askpass_path
    askpass_path="$(gcs_git_askpass_path)"

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

run_gcs_git_command() {
    local repo_url="$1"
    shift

    if is_github_ssh_repo_url "$repo_url"; then
        GIT_SSH_COMMAND="$(gcs_git_ssh_command)" git "$@"
    elif is_github_https_repo_url "$repo_url" && gcs_git_auth_enabled; then
        prepare_gcs_git_askpass
        env \
            GIT_TERMINAL_PROMPT=0 \
            GIT_ASKPASS_REQUIRE=force \
            GIT_ASKPASS="$(gcs_git_askpass_path)" \
            MDS_GIT_AUTH_USERNAME="${MDS_GIT_AUTH_USERNAME:-x-access-token}" \
            MDS_GIT_AUTH_TOKEN_FILE="${MDS_GIT_AUTH_TOKEN_FILE:-}" \
            MDS_GIT_AUTH_TOKEN="${MDS_GIT_AUTH_TOKEN:-}" \
            git -c credential.username="${MDS_GIT_AUTH_USERNAME:-x-access-token}" "$@"
    else
        git "$@"
    fi
}

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

# =============================================================================
# REPOSITORY SELECTION
# =============================================================================

# Display read-only warning for default repository
display_readonly_warning() {
    echo ""
    echo -e "${YELLOW}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}│${NC}  ${WHITE}⚠ DEFAULT REPOSITORY NOTICE${NC}"
    echo -e "${YELLOW}├────────────────────────────────────────────────────────────────────────────┤${NC}"
    echo -e "${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  You're using the default MDS repository:"
    echo -e "${YELLOW}│${NC}  ${DIM}github.com/${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show${NC}"
    echo -e "${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  ${WHITE}Unless you are the owner or a collaborator:${NC}"
    echo -e "${YELLOW}│${NC}    • ${RED}NO write access${NC} - you cannot push changes"
    echo -e "${YELLOW}│${NC}    • ${RED}NO custom git sync${NC} - drones pull official repo only"
    echo -e "${YELLOW}│${NC}    • ${GREEN}SITL/testing${NC} - works fine for simulation and testing"
    echo -e "${YELLOW}│${NC}    • ${GREEN}Drones can still pull${NC} - from official repo (not your changes)"
    echo -e "${YELLOW}│${NC}"
    echo -e "${YELLOW}│${NC}  ${WHITE}For custom configs/shows, fork the repository first.${NC}"
    echo -e "${YELLOW}│${NC}"
    echo -e "${YELLOW}└────────────────────────────────────────────────────────────────────────────┘${NC}"
    echo ""
}

# Verify fork configuration matches src/params.py (if using custom repo)
verify_fork_config() {
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local params_file="${install_dir}/src/params.py"

    # Only check if we have a custom repo and params.py exists
    if [[ -z "${REPO_URL:-}" ]] || [[ ! -f "$params_file" ]]; then
        return 0
    fi

    log_step "Verifying fork configuration..."

    local params_repo params_branch
    params_repo=$(grep -E "^GIT_REPO_URL\s*=" "$params_file" 2>/dev/null | cut -d'"' -f2 || echo "")
    params_branch=$(grep -E "^GIT_BRANCH\s*=" "$params_file" 2>/dev/null | cut -d'"' -f2 || echo "")

    local current_repo="${REPO_URL}"
    local current_branch="${BRANCH:-$GCS_DEFAULT_BRANCH}"

    # Convert both to comparable format (remove .git suffix)
    local clean_params_repo="${params_repo%.git}"
    local clean_current_repo="${current_repo%.git}"
    # Convert SSH to HTTPS format for comparison
    clean_params_repo=$(echo "$clean_params_repo" | sed 's|git@github.com:|https://github.com/|')
    clean_current_repo=$(echo "$clean_current_repo" | sed 's|git@github.com:|https://github.com/|')

    local mismatches=0

    if [[ -n "$params_repo" ]] && [[ "$clean_params_repo" != "$clean_current_repo" ]]; then
        echo ""
        echo -e "  ${YELLOW}⚠ Repository mismatch detected:${NC}"
        echo -e "    Configured (GCS): ${CYAN}${current_repo}${NC}"
        echo -e "    In params.py:     ${CYAN}${params_repo}${NC}"
        ((mismatches++))
    fi

    if [[ -n "$params_branch" ]] && [[ "$params_branch" != "$current_branch" ]]; then
        echo ""
        echo -e "  ${YELLOW}⚠ Branch mismatch detected:${NC}"
        echo -e "    Configured (GCS): ${CYAN}${current_branch}${NC}"
        echo -e "    In params.py:     ${CYAN}${params_branch}${NC}"
        ((mismatches++))
    fi

    if [[ $mismatches -gt 0 ]]; then
        echo ""
        echo -e "  ${WHITE}What this means:${NC}"
        echo -e "  ${DIM}• GCS dashboard startup uses /etc/mds/gcs.env (your selection above)${NC}"
        echo -e "  ${DIM}• params.py defaults are only used when env vars are not set${NC}"
        echo -e "  ${DIM}• Drones use their own params.py — update each drone separately${NC}"
        echo ""
        echo -e "  ${WHITE}No action needed${NC} — the dashboard start script exports your"
        echo -e "  selection as MDS_REPO_URL / MDS_BRANCH so the backend picks it up."
        echo ""
        log_warn "Configuration differences noted (GCS will use your selection)"
    else
        log_success "Fork configuration verified"
    fi

    return 0
}

# Prompt user to select repository (default or custom fork)
prompt_repository_selection() {
    # Skip if non-interactive or already have a custom repo URL
    if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
        log_info "Using default repository (non-interactive mode)"
        log_info "Repository: ${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show"
        log_info "Branch: ${BRANCH:-main-candidate}"
        return 0
    fi

    # If REPO_URL is already set (via CLI or env), use it
    if [[ -n "${REPO_URL:-}" ]]; then
        log_info "Using provided repository: ${REPO_URL}"
        log_info "Branch: ${BRANCH:-main-candidate}"
        return 0
    fi

    echo ""
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}Repository Selection${NC}"
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo ""
    echo -e "  Default: ${GREEN}github.com/${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show${NC}"
    echo -e "  Branch:  ${CYAN}${BRANCH:-main-candidate}${NC}"
    echo ""

    if confirm "Use default repository?" "y"; then
        log_info "Using: ${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show (${BRANCH:-main-candidate})"
    else
        echo ""
        echo -e "  ${WHITE}Enter your custom GitHub repository:${NC}"
        echo -e "  ${DIM}Examples: youruser   or   yourorg/customer-mds${NC}"
        local repo_spec repo_path
        read -p "  GitHub owner or owner/repo: " repo_spec </dev/tty

        if [[ -n "$repo_spec" ]]; then
            repo_path=$(normalize_github_repo_path "$repo_spec") || {
                log_warn "Invalid repository value, using default repository"
                echo ""
                return 0
            }
            REPO_URL="https://github.com/${repo_path}.git"
            export REPO_URL
            echo ""
            log_info "Repository: ${REPO_URL}"
            log_info "Branch: ${BRANCH:-main-candidate}"
        else
            log_warn "No repository provided, using default repository"
        fi
    fi
    echo ""
}

# =============================================================================
# SSH KEY MANAGEMENT
# =============================================================================

# Generate SSH deploy key
generate_ssh_key() {
    log_step "Generating SSH deploy key..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would generate SSH key at: ${GCS_SSH_KEY_PATH}${NC}"
        return 0
    fi

    # Create .ssh directory if needed
    mkdir -p "${HOME}/.ssh"
    chmod 700 "${HOME}/.ssh"

    # Check if key already exists
    if [[ -f "$GCS_SSH_KEY_PATH" ]]; then
        log_info "SSH key already exists: ${GCS_SSH_KEY_PATH}"
        return 0
    fi

    # Generate new key
    local hostname
    hostname=$(hostname)
    local email="mds-gcs@${hostname}"

    if ssh-keygen -t ed25519 -f "$GCS_SSH_KEY_PATH" -N "" -C "$email" 2>/dev/null; then
        chmod 600 "$GCS_SSH_KEY_PATH"
        chmod 644 "$GCS_SSH_KEY_PUB"
        log_success "SSH deploy key generated"
        return 0
    else
        log_error "Failed to generate SSH key"
        return 1
    fi
}

# Display SSH key and instructions
display_ssh_key_instructions() {
    echo ""
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo -e "${CYAN}|${NC}  ${WHITE}SSH DEPLOY KEY SETUP REQUIRED${NC}"
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"
    echo ""
    echo -e "  ${YELLOW}IMPORTANT: You need to add this deploy key to your GitHub repository.${NC}"
    echo ""
    echo -e "  ${WHITE}Your deploy key (copy this entire key):${NC}"
    echo -e "  ${DIM}───────────────────────────────────────────────────────────────────────────${NC}"
    echo ""
    cat "$GCS_SSH_KEY_PUB"
    echo ""
    echo -e "  ${DIM}───────────────────────────────────────────────────────────────────────────${NC}"
    echo ""
    echo -e "  ${WHITE}Steps to add the deploy key:${NC}"
    echo ""
    echo -e "  1. Go to your repository on GitHub"
    echo -e "  2. Click ${CYAN}Settings${NC} → ${CYAN}Deploy keys${NC} → ${CYAN}Add deploy key${NC}"
    echo -e "  3. Title: ${GREEN}MDS GCS - $(hostname)${NC}"
    echo -e "  4. Paste the key above"
    echo -e "  ${YELLOW}5. CHECK 'Allow write access' (REQUIRED for git sync features)${NC}"
    echo -e "  6. Click ${CYAN}Add key${NC}"
    echo -e "  7. Verify: ${GREEN}ssh -i ${GCS_SSH_KEY_PATH} -o IdentitiesOnly=yes -T git@github.com${NC}"
    echo ""
    echo -e "${CYAN}+------------------------------------------------------------------------------+${NC}"

    # Wait for user to read the instructions
    wait_for_keypress "Press any key after copying the key..."
}

# Configure SSH for GitHub
configure_ssh_github() {
    log_step "Configuring SSH for GitHub..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would configure SSH for GitHub${NC}"
        return 0
    fi

    prepare_gcs_ssh_runtime
    log_success "SSH GitHub access prepared"
    return 0
}

# Test SSH connection to GitHub
test_ssh_connection() {
    log_step "Testing SSH connection to GitHub..."

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would test SSH connection to GitHub${NC}"
        return 0
    fi

    local result
    prepare_gcs_ssh_runtime
    result=$(ssh \
        -T \
        -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o IdentitiesOnly=yes \
        -o StrictHostKeyChecking=accept-new \
        -i "${GCS_SSH_KEY_PATH}" \
        git@github.com 2>&1) || true

    if echo "$result" | grep -qi "successfully authenticated"; then
        log_success "SSH connection to GitHub verified"
        gcs_state_set_value "ssh_key_configured" "true"
        return 0
    else
        log_warn "SSH key not yet authorized on GitHub"
        return 1
    fi
}

# Wait for user to configure SSH key
wait_for_ssh_key() {
    if [[ "${NON_INTERACTIVE:-false}" == "true" ]]; then
        log_warn "SSH key not authorized in non-interactive mode"
        log_info "Falling back to HTTPS (read-only access, no git sync features)"
        USE_HTTPS="true"
        export USE_HTTPS
        return 0
    fi

    display_ssh_key_instructions

    while true; do
        echo ""
        if confirm "Have you added the deploy key to GitHub with write access?" "n"; then
            if test_ssh_connection; then
                return 0
            else
                log_warn "SSH authentication failed. Please verify the key was added correctly."
                echo ""
            fi
        else
            echo ""
            if confirm "Do you want to use HTTPS instead (no git sync features)?" "n"; then
                USE_HTTPS="true"
                export USE_HTTPS
                log_info "Switching to HTTPS mode"
                return 0
            fi
        fi
    done
}

# =============================================================================
# REPOSITORY OPERATIONS
# =============================================================================

# Get the repository URL to use
get_repo_url() {
    if [[ "${USE_HTTPS:-false}" == "true" ]]; then
        if [[ -n "${REPO_URL:-}" ]]; then
            # Convert SSH URL to HTTPS if needed
            echo "$REPO_URL" | sed 's|git@github.com:|https://github.com/|'
        else
            echo "$GCS_DEFAULT_REPO"
        fi
    else
        if [[ -n "${REPO_URL:-}" ]]; then
            # Convert HTTPS URL to SSH if needed
            echo "$REPO_URL" | sed 's|https://github.com/|git@github.com:|'
        else
            echo "$GCS_DEFAULT_REPO_SSH"
        fi
    fi
}

# Clone or update repository
clone_or_update_repo() {
    local repo_url
    repo_url=$(get_repo_url)
    local branch="${BRANCH:-$GCS_DEFAULT_BRANCH}"
    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"

    log_step "Repository: $repo_url"
    log_step "Branch: $branch"
    log_step "Install directory: $install_dir"

    if is_dry_run; then
        echo -e "  ${DIM}[DRY-RUN] Would clone/update repository${NC}"
        return 0
    fi

    # Check if already in a git repo
    if [[ -d "${install_dir}/.git" ]]; then
        cd "$install_dir" || return 1

        # Check if remote URL needs to be updated (user selected different fork)
        local current_remote
        current_remote=$(git remote get-url origin 2>/dev/null || echo "")

        if [[ "$current_remote" != "$repo_url" ]]; then
            log_info "Updating remote URL..."
            log_info "  From: $current_remote"
            log_info "  To:   $repo_url"
            run_gcs_git_command "$repo_url" remote set-url origin "$repo_url" || {
                log_error "Failed to update remote URL"
                return 1
            }
            log_success "Remote URL updated"
        fi

        configure_repo_ssh_command "$install_dir" "$repo_url"
        log_info "Fetching from remote..."

        # Fetch and checkout branch
        start_progress "Fetching from remote" "depends on network speed"
        run_gcs_git_command "$repo_url" fetch origin "$branch" >/dev/null 2>&1
        local fetch_rc=$?
        stop_progress

        if [[ $fetch_rc -ne 0 ]]; then
            log_warn "Could not fetch from remote - check your access"
        fi

        # Check current branch
        local current_branch
        current_branch=$(git branch --show-current 2>/dev/null)

        if [[ "$current_branch" != "$branch" ]]; then
            log_info "Switching from $current_branch to $branch"
            run_gcs_git_command "$repo_url" checkout "$branch" 2>/dev/null || run_gcs_git_command "$repo_url" checkout -b "$branch" "origin/$branch" 2>/dev/null || {
                log_error "Failed to checkout branch: $branch"
                return 1
            }
        fi

        # Pull latest changes
        start_progress "Pulling latest changes"
        run_gcs_git_command "$repo_url" pull origin "$branch" >/dev/null 2>&1
        local pull_rc=$?
        stop_progress

        if [[ $pull_rc -ne 0 ]]; then
            log_warn "Could not pull latest changes (may have local modifications)"
        fi

        local commit
        commit=$(git rev-parse --short HEAD 2>/dev/null)
        log_success "Repository updated (commit: $commit)"
        gcs_state_set_value "repo_commit" "$commit"

    else
        log_info "Cloning repository..."

        # Ensure parent directory exists
        local parent_dir
        parent_dir=$(dirname "$install_dir")
        mkdir -p "$parent_dir"

        local clone_rc=0
        start_progress "Cloning repository" "may take 1-3 min for first clone"
        run_gcs_git_command "$repo_url" clone -b "$branch" "$repo_url" "$install_dir" >/dev/null 2>&1 || clone_rc=$?
        if [[ $clone_rc -eq 0 ]]; then
            stop_progress
            cd "$install_dir" || return 1
            configure_repo_ssh_command "$install_dir" "$repo_url"
            local commit
            commit=$(git rev-parse --short HEAD 2>/dev/null)
            log_success "Repository cloned (commit: $commit)"
            gcs_state_set_value "repo_commit" "$commit"
        else
            stop_progress
            log_error "Failed to clone repository"
            return 1
        fi
    fi

    # Store repo info in state
    gcs_state_set_value "repo_url" "$repo_url"
    gcs_state_set_value "repo_branch" "$branch"
    gcs_state_set_value "install_dir" "$install_dir"

    # Fix repository ownership when running as sudo
    # Without this, venv/node_modules created later inherit root ownership
    # and the invoking user gets permission errors at runtime
    local target_user="${SUDO_USER:-}"
    if [[ -n "$target_user" ]] && [[ "$target_user" != "root" ]]; then
        log_info "Fixing repository ownership for user: $target_user"
        chown -R "$target_user":"$target_user" "$install_dir" 2>/dev/null || true
    fi

    return 0
}

# =============================================================================
# MAIN PHASE RUNNER
# =============================================================================

run_repository_phase() {
    print_phase_header "4" "Repository Setup" "9"

    # Check skip flag
    if [[ "${SKIP_REPO:-false}" == "true" ]]; then
        log_info "Skipping repository setup (--skip-repo)"
        return 0
    fi

    local install_dir="${GCS_INSTALL_DIR:-$(pwd)}"
    local current_remote current_branch current_commit

    # Get current repo info if exists
    if [[ -d "${install_dir}/.git" ]]; then
        current_remote=$(cd "$install_dir" && git remote get-url origin 2>/dev/null || echo "unknown")
        current_branch=$(cd "$install_dir" && git branch --show-current 2>/dev/null || echo "unknown")
        current_commit=$(cd "$install_dir" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    fi

    # =========================================================================
    # STEP 1: Repository Selection (WHAT repo to use)
    # =========================================================================
    print_section "Step 1: Repository Selection"

    # Track if using default repo for read-only warning
    local using_default_repo="true"

    if can_prompt && [[ -z "${REPO_URL:-}" ]]; then
        echo ""
        echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
        echo -e "${CYAN}│${NC}  ${WHITE}Do you have your own fork of the MDS repository?${NC}"
        echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
        echo -e "${CYAN}│${NC}"
        echo -e "${CYAN}│${NC}  ${WHITE}[1]${NC} ${GREEN}No - Use default repository (Recommended for testing)${NC}"
        echo -e "${CYAN}│${NC}      github.com/${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show"
        echo -e "${CYAN}│${NC}      ${YELLOW}⚠ Limited: SITL/testing only unless you have collaborator access${NC}"
        echo -e "${CYAN}│${NC}"
        echo -e "${CYAN}│${NC}  ${WHITE}[2]${NC} Yes - I have my own fork"
        echo -e "${CYAN}│${NC}      ${GREEN}✓ Full write access for production use${NC}"
        echo -e "${CYAN}│${NC}      Requires: SSH deploy key setup"
        echo -e "${CYAN}│${NC}"
        echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
        echo ""

        local repo_choice
        read -p "  Select [1/2]: " repo_choice </dev/tty
        repo_choice=${repo_choice:-1}

        if [[ "$repo_choice" == "2" ]]; then
            using_default_repo="false"
            echo ""
            local github_user custom_branch
            read -p "  Your GitHub username: " github_user </dev/tty

            if [[ -n "$github_user" ]]; then
                read -p "  Branch name [main-candidate]: " custom_branch </dev/tty
                custom_branch=${custom_branch:-main-candidate}

                REPO_URL="https://github.com/${github_user}/mavsdk_drone_show.git"
                BRANCH="$custom_branch"
                export REPO_URL BRANCH

                log_info "Using fork: ${github_user}/mavsdk_drone_show"
                log_info "Branch: ${BRANCH}"

                # Fork users need SSH for write access
                echo ""
                log_info "Fork selected - SSH access recommended for git sync features"
            else
                log_warn "No username provided, using official repository"
                using_default_repo="true"
            fi
        else
            log_info "Using official repository: ${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show"
            log_info "Branch: ${BRANCH:-main-candidate}"

            # Show read-only warning for default repo
            display_readonly_warning

            # Ask if they have SSH access (owner/collaborator)
            if confirm "Do you have SSH write access to this repository? (owner/collaborator)" "n"; then
                log_info "SSH access confirmed - enabling git sync features"
                using_default_repo="false"  # Treat as having write access
            else
                log_info "Using HTTPS (read-only) - suitable for SITL and testing"
                USE_HTTPS="true"
                export USE_HTTPS
            fi
        fi
        echo ""
    else
        # Non-interactive or REPO_URL already set
        if [[ -n "${REPO_URL:-}" ]]; then
            log_info "Repository: ${REPO_URL}"
            using_default_repo="false"
        else
            log_info "Repository: ${GCS_DEFAULT_REPO_OWNER}/mavsdk_drone_show (default)"
        fi
        log_info "Branch: ${BRANCH:-main-candidate}"
        echo ""
    fi

    # Store repo type in state
    if [[ "$using_default_repo" == "true" ]]; then
        gcs_state_set_value "repo_type" "default"
    else
        gcs_state_set_value "repo_type" "fork"
    fi

    # Prompt for branch change (interactive mode, default repo only)
    if can_prompt && [[ -z "${REPO_URL:-}" ]]; then
        local current_branch_display="${BRANCH:-$GCS_DEFAULT_BRANCH}"
        echo -e "  Current branch: ${CYAN}${current_branch_display}${NC}"
        local new_branch=""
        read -p "  Change branch? [branch name or Enter to keep]: " new_branch </dev/tty
        if [[ -n "$new_branch" ]]; then
            BRANCH="$new_branch"
            export BRANCH
            log_info "Branch changed to: ${BRANCH}"
        fi
        echo ""
    fi

    # =========================================================================
    # STEP 2: Access Mode (HOW to access the repo)
    # =========================================================================
    # Skip if HTTPS was already selected in Step 1 (read-only default repo)
    if [[ "${USE_HTTPS:-}" != "true" ]]; then
        print_section "Step 2: Access Mode"

        if can_prompt; then
            echo ""
            echo -e "${CYAN}┌────────────────────────────────────────────────────────────────────────────┐${NC}"
            echo -e "${CYAN}│${NC}  ${WHITE}How do you want to access the repository?${NC}"
            echo -e "${CYAN}├────────────────────────────────────────────────────────────────────────────┤${NC}"
            echo -e "${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}  ${WHITE}[1]${NC} ${GREEN}HTTPS (Simpler setup)${NC}"
            echo -e "${CYAN}│${NC}      - No SSH keys needed"
            echo -e "${CYAN}│${NC}      - Pull updates anytime"
            echo -e "${CYAN}│${NC}      - Push requires manual: git push"
            echo -e "${CYAN}│${NC}"
            echo -e "${CYAN}│${NC}  ${WHITE}[2]${NC} SSH with deploy key ${GREEN}(Recommended for production)${NC}"
            echo -e "${CYAN}│${NC}      - Enables automatic git sync from dashboard"
            echo -e "${CYAN}│${NC}      - Drones can pull updates automatically"
            echo -e "${CYAN}│${NC}      - Requires adding deploy key to GitHub"
            echo -e "${CYAN}│${NC}"
            echo -e "${CYAN}└────────────────────────────────────────────────────────────────────────────┘${NC}"
            echo ""

            local access_choice
            read -p "  Select access mode [2]: " access_choice </dev/tty
            access_choice=${access_choice:-2}

            if [[ "$access_choice" == "1" ]]; then
                USE_HTTPS="true"
                export USE_HTTPS
                log_info "Using HTTPS access (simple setup)"
            else
                USE_HTTPS="false"
                export USE_HTTPS
                log_info "Using SSH access (will set up deploy key)"
            fi
            echo ""
        else
            if gcs_should_use_https_access "${REPO_URL:-}"; then
                USE_HTTPS="true"
                export USE_HTTPS
                log_info "Access mode: HTTPS (non-interactive inferred from repository/auth settings)"
            else
                if [[ "${NON_INTERACTIVE:-false}" != "true" ]]; then
                    log_warn "No interactive TTY detected; defaulting to SSH access mode"
                fi
                log_info "Access mode: SSH (non-interactive default)"
            fi
            echo ""
        fi
    else
        log_info "Access mode: HTTPS (read-only, set in Step 1)"
        gcs_state_set_value "access_method" "https"
        echo ""
    fi

    # =========================================================================
    # STEP 3: SSH Key Setup (only if SSH mode selected)
    # =========================================================================
    if [[ "${USE_HTTPS:-false}" != "true" ]]; then
        print_section "Step 3: SSH Deploy Key Setup"
        log_info "Setting up SSH key for repository access..."
        echo ""

        generate_ssh_key || return 1
        configure_ssh_github || return 1

        if ! test_ssh_connection; then
            wait_for_ssh_key || return 1
        fi
    fi

    # =========================================================================
    # STEP 4: Apply Configuration
    # =========================================================================
    print_section "Applying Repository Configuration"
    clone_or_update_repo || return 1

    # Store access method in state
    if [[ "${USE_HTTPS:-false}" == "true" ]]; then
        gcs_state_set_value "access_method" "https"
    else
        gcs_state_set_value "access_method" "ssh"
    fi

    # =========================================================================
    # STEP 5: Fork Verification (for custom repos)
    # =========================================================================
    if [[ -n "${REPO_URL:-}" ]]; then
        print_section "Repo Configuration Check"
        verify_fork_config
    fi

    echo ""
    log_success "Repository phase completed"
    return 0
}
