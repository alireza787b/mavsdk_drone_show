#!/bin/bash
#
# create_backup_restore_scripts.sh
#
# This generator script does the following:
# 1. Checks for prerequisites (rsync and dos2unix) and installs them if missing.
# 2. Creates/overwrites two scripts in the user's home directory:
#    - backup_msd  : Backs up ~/mavsdk_drone_show to ~/mavsdk_drone_show_backup.
#    - restore_msd : Restores ~/mavsdk_drone_show from ~/mavsdk_drone_show_backup.
#       It removes the current repository folder, copies the backup (preserving it),
#       then changes directory to the restored repository, runs 'git stash' and 'git pull',
#       and optionally reboots the system.
# 3. Runs an initial backup automatically.
#
# Non-interactive by default.
#
set -euo pipefail

###################################
# Configurable Settings
###################################
BACKUP_SCRIPT="$HOME/backup_msd"
RESTORE_SCRIPT="$HOME/restore_msd"
GEN_LOG_FILE="/tmp/create_backup_restore.log"  # Log for this generator script
SRC_DIR="$HOME/mavsdk_drone_show"
BAK_DIR="$HOME/mavsdk_drone_show_backup"

###################################
# Logging Function for Generator
###################################
gen_log() {
  local msg="$1"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [create_backup_restore] $msg" | tee -a "$GEN_LOG_FILE"
}

###################################
# Check and Install Prerequisites
###################################
check_prerequisite() {
  local cmd="$1"
  local pkg="$2"  # package name for installation if needed
  if ! command -v "$cmd" &>/dev/null; then
    gen_log "Prerequisite '$cmd' not found. Installing package '$pkg'..."
    apt-get update && apt-get install -y "$pkg"
  else
    gen_log "Prerequisite '$cmd' found."
  fi
}

gen_log "Checking prerequisites..."
check_prerequisite rsync rsync
check_prerequisite dos2unix dos2unix
gen_log "All prerequisites are in place."

###################################
# Create backup_msd Script
###################################
create_backup_script() {
  gen_log "Creating backup_msd script at $BACKUP_SCRIPT ..."
  cat << 'EOF' > "$BACKUP_SCRIPT"
#!/bin/bash
#
# backup_msd
#
# Backs up the mavsdk_drone_show repository (SRC_DIR) to mavsdk_drone_show_backup (BAK_DIR).
# Overwrites any existing backup without prompting.
# Progress is shown using rsync's progress output.
#
set -euo pipefail

###################################
# Configuration
###################################
SRC_DIR="$HOME/mavsdk_drone_show"
BAK_DIR="$HOME/mavsdk_drone_show_backup"
LOG_FILE="/tmp/backup_msd.log"

###################################
# Logging Function
###################################
log() {
  local msg="$1"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [backup_msd] $msg" | tee -a "$LOG_FILE"
}

###################################
# Main Backup Routine
###################################
log "Starting backup from ${SRC_DIR} to ${BAK_DIR}..."

# 1) Check that the source directory exists.
if [ ! -d "$SRC_DIR" ]; then
  log "ERROR: Source directory ${SRC_DIR} does not exist. Backup aborted."
  exit 1
fi

# 2) Remove existing backup directory if it exists.
if [ -d "$BAK_DIR" ]; then
  log "Removing existing backup directory ${BAK_DIR}..."
  rm -rf "$BAK_DIR"
fi

# 3) Use a temporary directory for a safe backup.
TMP_BAK_DIR="${BAK_DIR}.tmp"
[ -d "$TMP_BAK_DIR" ] && rm -rf "$TMP_BAK_DIR"
mkdir -p "$TMP_BAK_DIR"

log "Copying files with progress indicator..."
rsync -a --delete --info=progress2 "$SRC_DIR/" "$TMP_BAK_DIR/"

log "Renaming temporary backup directory to final ${BAK_DIR}..."
mv "$TMP_BAK_DIR" "$BAK_DIR"

log "Backup completed successfully."
EOF

  chmod +x "$BACKUP_SCRIPT"
  dos2unix "$BACKUP_SCRIPT"
  gen_log "backup_msd script created and converted to Unix format."
}

###################################
# Create restore_msd Script
###################################
create_restore_script() {
  gen_log "Creating restore_msd script at $RESTORE_SCRIPT ..."
  cat << 'EOF' > "$RESTORE_SCRIPT"
#!/bin/bash
#
# restore_msd
#
# Restores the mavsdk_drone_show repository from mavsdk_drone_show_backup.
# Removes the current repository folder, then copies the backup to the original location
# (backup folder is preserved). After restoration, it changes directory to the restored
# repository, runs 'git stash' and 'git pull', and optionally reboots the system.
#
set -euo pipefail

###################################
# Configuration
###################################
SRC_DIR="$HOME/mavsdk_drone_show"
BAK_DIR="$HOME/mavsdk_drone_show_backup"
LOG_FILE="/tmp/restore_msd.log"
DO_REBOOT=false   # Set to true to enable system reboot after restore

###################################
# Logging Function
###################################
log() {
  local msg="$1"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [restore_msd] $msg" | tee -a "$LOG_FILE"
}

###################################
# Main Restore Routine
###################################
log "Starting restore from ${BAK_DIR} to ${SRC_DIR}..."

# 1) Verify backup directory exists.
if [ ! -d "$BAK_DIR" ]; then
  log "ERROR: Backup directory ${BAK_DIR} does not exist. Restore aborted."
  exit 1
fi

# 2) Remove the current repository directory.
if [ -d "$SRC_DIR" ]; then
  log "Removing current repository directory ${SRC_DIR}..."
  rm -rf "$SRC_DIR"
fi

# 3) Restore the backup by copying it to the original location (backup preserved).
log "Copying backup to ${SRC_DIR} (backup preserved)..."
rsync -a --delete "$BAK_DIR/" "$SRC_DIR/"

# 4) Change directory to the restored repository and update it with git.
log "Changing to restored directory ${SRC_DIR}..."
cd "$SRC_DIR"

if [ -d ".git" ]; then
  log "Running 'git stash'..."
  git stash
  log "Running 'git pull'..."
  git pull
else
  log "Directory ${SRC_DIR} is not a git repository. Skipping git operations."
fi

source venv/bin/activate
pip install --no-deps -r requirements.txt

# 5) Optionally reboot the system.
if [ "$DO_REBOOT" = true ]; then
  log "Rebooting system as per configuration..."
  reboot
fi

log "Restore completed successfully."
EOF

  chmod +x "$RESTORE_SCRIPT"
  dos2unix "$RESTORE_SCRIPT"
  gen_log "restore_msd script created and converted to Unix format."
}

###################################
# Main Execution
###################################
gen_log "==============================================="
gen_log "Creating backup_msd and restore_msd scripts..."
gen_log "==============================================="

# Create the two scripts.
create_backup_script
create_restore_script

# Run an initial backup automatically.
gen_log "Running initial backup to ensure a valid backup copy..."
if ! "$BACKUP_SCRIPT"; then
  gen_log "Initial backup failed! Please check the logs or run $BACKUP_SCRIPT manually."
  exit 1
fi

gen_log "All done. Scripts created in $HOME and initial backup completed successfully."
gen_log "Future usage:"
gen_log "  Run '$HOME/backup_msd' to create/update the backup."
gen_log "  Run '$HOME/restore_msd' to restore the repository from the backup."
exit 0
