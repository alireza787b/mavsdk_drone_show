#!/bin/bash
#
# create_backup_restore_scripts.sh
#
# Generates two scripts in the user's home directory:
#   1) backup_msd  : Backs up the ~/mavsdk_drone_show to ~/mavsdk_drone_show_backup
#   2) restore_msd : Restores ~/mavsdk_drone_show from ~/mavsdk_drone_show_backup
#
# After creation, this script triggers an initial backup automatically.

set -euo pipefail

###################################
# Configurable Settings
###################################
BACKUP_SCRIPT="$HOME/backup_msd"
RESTORE_SCRIPT="$HOME/restore_msd"
LOG_FILE="/tmp/create_backup_restore.log"  # Log for this generator script

###################################
# Logging Function
###################################
log() {
  local msg="$1"
  echo "$(date +'%Y-%m-%d %H:%M:%S') [create_backup_restore_scripts] $msg" | tee -a "$LOG_FILE"
}

###################################
# Script Creation
###################################
create_backup_script() {
  log "Creating $BACKUP_SCRIPT ..."
  cat << 'EOF' > "$BACKUP_SCRIPT"
#!/bin/bash
#
# backup_msd
#
# Creates a backup of the user's mavsdk_drone_show repo in ~/mavsdk_drone_show_backup.
#
# By default, any existing backup is overwritten without prompts.
# Adjust the flags below to change behavior.

set -euo pipefail

###################################
# Configuration
###################################
PROMPT_USER=false           # If true, will ask before overwriting backup
SRC_DIR="\$HOME/mavsdk_drone_show"
BAK_DIR="\$HOME/mavsdk_drone_show_backup"
LOG_FILE="/tmp/backup_msd.log"

###################################
# Logging Function
###################################
log() {
  local msg="\$1"
  echo "\$(date +'%Y-%m-%d %H:%M:%S') [backup_msd] \$msg" | tee -a "\$LOG_FILE"
}

###################################
# Main Backup Routine
###################################
log "Starting backup from \${SRC_DIR} to \${BAK_DIR}"

# 1) Check if source directory exists
if [ ! -d "\$SRC_DIR" ]; then
  log "ERROR: Source directory \${SRC_DIR} does not exist. Backup aborted."
  exit 1
fi

# 2) Handle existing backup
if [ -d "\$BAK_DIR" ]; then
  if [ "\$PROMPT_USER" = true ]; then
    echo "Backup directory (\$BAK_DIR) already exists. Overwrite? (y/N)"
    read -r answer
    if [ "\$answer" != "y" ] && [ "\$answer" != "Y" ]; then
      log "User aborted overwrite."
      exit 0
    fi
  fi
  log "Removing existing backup directory \${BAK_DIR}"
  rm -rf "\$BAK_DIR"
fi

# 3) Perform backup safely with a temp directory
TMP_BAK_DIR="\${BAK_DIR}.tmp"
if [ -d "\$TMP_BAK_DIR" ]; then
  rm -rf "\$TMP_BAK_DIR"
fi
mkdir -p "\$TMP_BAK_DIR"

# Using rsync for a robust copy
log "Copying files to temporary backup directory \${TMP_BAK_DIR}"
rsync -a --delete "\$SRC_DIR/" "\$TMP_BAK_DIR/"

log "Renaming temporary backup directory to final \${BAK_DIR}"
mv "\$TMP_BAK_DIR" "\$BAK_DIR"

log "Backup completed successfully."
EOF

  chmod +x "$BACKUP_SCRIPT"
  log "Created and made $BACKUP_SCRIPT executable."
}

create_restore_script() {
  log "Creating $RESTORE_SCRIPT ..."
  cat << 'EOF' > "$RESTORE_SCRIPT"
#!/bin/bash
#
# restore_msd
#
# Restores the ~/mavsdk_drone_show directory from ~/mavsdk_drone_show_backup.
#
# By default, it DELETES the backup after restore is complete
# because the backup folder is MOVED to the repo folder.
# Adjust the flags below to customize behavior.

set -euo pipefail

###################################
# Configuration
###################################
PROMPT_USER=false            # If true, will ask user before restoring
KEEP_BACKUP_AFTER_RESTORE=false  # If true, will COPY instead of MOVE, so the backup stays
SRC_DIR="\$HOME/mavsdk_drone_show"
BAK_DIR="\$HOME/mavsdk_drone_show_backup"
LOG_FILE="/tmp/restore_msd.log"

###################################
# Logging Function
###################################
log() {
  local msg="\$1"
  echo "\$(date +'%Y-%m-%d %H:%M:%S') [restore_msd] \$msg" | tee -a "\$LOG_FILE"
}

###################################
# Main Restore Routine
###################################
log "Starting restore from \${BAK_DIR} to \${SRC_DIR}"

# 1) Check if backup directory exists
if [ ! -d "\$BAK_DIR" ]; then
  log "ERROR: Backup directory \${BAK_DIR} does not exist. Cannot restore."
  exit 1
fi

# 2) Prompt user if configured
if [ "\$PROMPT_USER" = true ]; then
  echo "Are you sure you want to restore from \${BAK_DIR}? This will overwrite \${SRC_DIR}. (y/N)"
  read -r answer
  if [ "\$answer" != "y" ] && [ "\$answer" != "Y" ]; then
    log "User aborted restore."
    exit 0
  fi
fi

# 3) Remove existing SRC_DIR
if [ -d "\$SRC_DIR" ]; then
  log "Removing current repository directory \${SRC_DIR}"
  rm -rf "\$SRC_DIR"
fi

# 4) Move or Copy backup to SRC_DIR
if [ "\$KEEP_BACKUP_AFTER_RESTORE" = true ]; then
  # COPY
  log "Copying backup to \${SRC_DIR}; backup remains intact."
  rsync -a --delete "\$BAK_DIR/" "\$SRC_DIR/"
else
  # MOVE
  log "Moving backup to \${SRC_DIR}; backup will no longer exist afterward."
  mv "\$BAK_DIR" "\$SRC_DIR"
fi

log "Restore completed successfully."
EOF

  chmod +x "$RESTORE_SCRIPT"
  log "Created and made $RESTORE_SCRIPT executable."
}

###################################
# Main Execution
###################################
log "==============================================="
log "Creating backup_msd and restore_msd scripts..."
log "==============================================="
create_backup_script
create_restore_script

# Perform an initial backup automatically
log "Running initial backup to ensure a valid backup copy..."
"$BACKUP_SCRIPT" || {
  log "Initial backup failed! Please check logs."
  exit 1
}

log "All done. Scripts created in HOME directory and initial backup completed."
log "You can now run:"
log "  $HOME/backup_msd   # to manually re-backup"
log "  $HOME/restore_msd  # to restore from backup"
exit 0
