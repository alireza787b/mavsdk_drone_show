#!/bin/bash

# =============================================================================
# Function: Ensure Polkit Rule for Reboot Exists
# =============================================================================
configure_polkit_for_reboot() {
    local polkit_rule_path="/etc/polkit-1/rules.d/50-droneshow-reboot.rules"
    local expected_rule_content="polkit.addRule(function(action, subject) {
    if ((action.id == \"org.freedesktop.login1.reboot\" ||
         action.id == \"org.freedesktop.login1.power-off\" ||
         action.id == \"org.freedesktop.login1.hibernate\" ||
         action.id == \"org.freedesktop.login1.suspend\") &&
        subject.isInGroup(\"droneshow\")) {
        return polkit.Result.YES;
    }
});"

    # Check if the Polkit rule file exists
    if [[ -f "$polkit_rule_path" ]]; then
        echo "Polkit rule file exists at $polkit_rule_path. Checking contents..."

        # Check if the rule for the 'droneshow' user exists in the file
        if grep -q "subject.isInGroup(\"droneshow\")" "$polkit_rule_path"; then
            echo "Polkit rule for 'droneshow' reboot already exists. No changes needed."
        else
            echo "Polkit rule file exists, but the 'droneshow' rule is missing. Updating the rule..."
            add_polkit_reboot_rule "$polkit_rule_path" "$expected_rule_content"
        fi
    else
        echo "Polkit rule file does not exist. Creating it with the necessary reboot rule for 'droneshow'..."
        add_polkit_reboot_rule "$polkit_rule_path" "$expected_rule_content"
    fi
}

# =============================================================================
# Function: Add or Update Polkit Rule for Reboot
# =============================================================================
add_polkit_reboot_rule() {
    local polkit_rule_path="$1"
    local rule_content="$2"

    # Create or update the Polkit rule file with the expected content
    sudo tee "$polkit_rule_path" > /dev/null << EOF
$rule_content
EOF

    # Set correct permissions
    sudo chmod 644 "$polkit_rule_path"
    echo "Polkit rule added or updated successfully at $polkit_rule_path."
}

# =============================================================================
# Main Script (Example of Usage)
# =============================================================================

# Ensure the Polkit rule for reboot is correctly set up
configure_polkit_for_reboot
