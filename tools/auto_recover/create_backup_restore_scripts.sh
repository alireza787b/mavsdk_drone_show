#!/bin/bash
#
# create_backup_restore_scripts.sh
#
# Generates (or overwrites) two scripts in the user's home directory:
#   1) ~/backup_msd  : Backs up ~/mavsdk_drone_show -> ~/mavsdk_drone_show_backup
#   2) ~/restore_msd : Restores ~/mavsdk_drone_show from ~/mavsdk_drone_show_backup
#
# After creating them, it performs an initial backup automatically.
#
# Non-interactive by default (no user prompts). 
# Adjust flags in the generated scripts if needed.

set -euo pipefail

###################################
# Configurable Settings
###################################
BACKUP_SCRIPT="$HOME/backup_msd"
RESTORE_SCRIPT="$HOME/restore_msd"
LOG_FILE="/tmp/create_backup_restore.log"  # Log for this generator script
SRC_DIR="$HOME/mavsdk_drone_show"
BAK_DIR="$HOME/mavsdk_drone_show_backup"

###################################
# Logging Function
###################################
log() {
  local msg="$1"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [create_backup_restore] $msg" | tee -a "$LOG_FILE"
}

###################################
# Create backup_msd
###################################
create_backup_script() {
  cat << 'EOF' > "$BACKUP_SCRIPT"
#!/bin/bash
#
# backup_msd
#
# Creates a backup of mavsdk_drone_show repo in ~/mavsdk_drone_show_backup.
# Overwrites existing backup with no prompts by default.

set -euo pipefail

###################################
# Configuration
###################################
PROMPT_USER=false    # if true => ask before overwriting
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
log "Starting backup from ${SRC_DIR} to ${BAK_DIR}"

# 1) Check source directory
if [ ! -d "$SRC_DIR" ]; then
  log "ERROR: Source directory ${SRC_DIR} does not exist. Backup aborted."
  exit 1
fi

# 2) If backup directory exists, remove or prompt
if [ -d "$BAK_DIR" ]; then
  if [ "$PROMPT_USER" = true ]; then
    echo "Backup directory ($BAK_DIR) already exists. Overwrite? (y/N)"
    read -r answer
    if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
      log "User aborted overwrite."
      exit 0
    fi
  fi
  log "Removing existing backup directory ${BAK_DIR}"
  rm -rf "$BAK_DIR"
fi

# 3) Create a temp backup directory, then move it into place
TMP_BAK_DIR="${BAK_DIR}.tmp"
[ -d "$TMP_BAK_DIR" ] && rm -rf "$TMP_BAK_DIR"

mkdir -p "$TMP_BAK_DIR"
log "Copying files to ${TMP_BAK_DIR}"

# Use rsync for a robust copy
rsync -a --delete "$SRC_DIR/" "$TMP_BAK_DIR/"

log "Renaming temp backup dir to final ${BAK_DIR}"
mv "$TMP_BAK_DIR" "$BAK_DIR"

log "Backup completed successfully."
EOF

  chmod +x "$BACKUP_SCRIPT"
  dos2unix "$BACKUP_SCRIPT"  # Ensure Unix line endings
  log "Created and converted $BACKUP_SCRIPT to Unix format."
}

###################################
# Create restore_msd
###################################
create_restore_script() {
  cat << 'EOF' > "$RESTORE_SCRIPT"
#!/bin/bash
#
# restore_msd
#
# Restores ~/mavsdk_drone_show from ~/mavsdk_drone_show_backup.
# By default, moves the backup => the backup no longer exists after restore.

set -euo pipefail

###################################
# Configuration
###################################
PROMPT_USER=false                 # If true => ask user before restoring
KEEP_BACKUP_AFTER_RESTORE=false  # If true => copy instead of move
SRC_DIR="$HOME/mavsdk_drone_show"
BAK_DIR="$HOME/mavsdk_drone_show_backup"
LOG_FILE="/tmp/restore_msd.log"

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
log "Starting restore from ${BAK_DIR} to ${SRC_DIR}"

# 1) Check if backup directory exists
if [ ! -d "$BAK_DIR" ]; then
  log "ERROR: Backup directory ${BAK_DIR} does not exist. Cannot restore."
  exit 1
fi

# 2) If prompting is enabled, confirm
if [ "$PROMPT_USER" = true ]; then
  echo "Are you sure you want to restore? This will overwrite ${SRC_DIR}. (y/N)"
  read -r answer
  if [ "$answer" != "y" ] && [ "$answer" != "Y" ]; then
    log "User aborted restore."
    exit 0
  fi
fi

# 3) Remove existing repo
if [ -d "$SRC_DIR" ]; then
  log "Removing existing ${SRC_DIR}"
  rm -rf "$SRC_DIR"
fi

# 4) Move or Copy from BAK_DIR => SRC_DIR
if [ "$KEEP_BACKUP_AFTER_RESTORE" = true ]; then
  log "Copying backup => ${SRC_DIR}; preserving backup folder."
  rsync -a --delete "$BAK_DIR/" "$SRC_DIR/"
else
  log "Moving backup => ${SRC_DIR}; backup folder will be deleted."
  mv "$BAK_DIR" "$SRC_DIR"
fi

log "Restore completed successfully."
EOF

  chmod +x "$RESTORE_SCRIPT"
  dos2unix "$RESTORE_SCRIPT"
  log "Created and converted $RESTORE_SCRIPT to Unix format."
}

###################################
# Main Execution
###################################
log "==============================================="
log "Creating backup_msd and restore_msd scripts..."
log "==============================================="

# 1) Create the two scripts
create_backup_script
create_restore_script

# 2) Perform an initial backup automatically
log "Running initial backup to ensure a valid backup copy..."
if ! "$BACKUP_SCRIPT"; then
  log "Initial backup failed! Please check logs or run $BACKUP_SCRIPT manually."
  exit 1
fi

log "All done. Scripts created in $HOME and initial backup completed."
log "You can now run:"
log "  $HOME/backup_msd    # to backup"
log "  $HOME/restore_msd   # to restore from backup"
exit 0
