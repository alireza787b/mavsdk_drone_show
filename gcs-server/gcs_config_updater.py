"""
GCS Configuration Updater
Handles programmatic editing of src/params.py for GCS IP configuration
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

def validate_ip_address(ip_string):
    """
    Validate IP address format and range

    Args:
        ip_string (str): IP address to validate

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    # Check format: XXX.XXX.XXX.XXX
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(ip_pattern, ip_string):
        return False, 'Invalid IP address format. Expected: XXX.XXX.XXX.XXX'

    # Check octet ranges (0-255)
    octets = ip_string.split('.')
    try:
        for octet in octets:
            num = int(octet)
            if not (0 <= num <= 255):
                return False, f'IP octet {num} out of range (must be 0-255)'
    except ValueError:
        return False, 'IP octets must be numeric'

    return True, None

def update_gcs_ip_in_params(new_ip):
    """
    Update GCS_IP value in src/params.py file using safe regex replacement

    This function:
    1. Validates the new IP address format and range
    2. Reads the current params.py file
    3. Extracts the current IP for logging
    4. Performs regex-based replacement
    5. Validates Python syntax before writing
    6. Writes the updated file

    Args:
        new_ip (str): New GCS IP address

    Returns:
        dict: {
            'success': bool,
            'old_ip': str (if successful),
            'new_ip': str,
            'file_path': str (if successful),
            'error': str (if failed)
        }
    """
    # Get base directory (parent of gcs-server)
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params_file = os.path.join(base_dir, 'src', 'params.py')

    logger.info(f"[GCS Config] Updating GCS IP in {params_file}")

    # Step 1: Validate IP format and range
    is_valid, error_msg = validate_ip_address(new_ip)
    if not is_valid:
        logger.error(f"[GCS Config] IP validation failed: {error_msg}")
        return {'success': False, 'error': error_msg}

    logger.info(f"[GCS Config] ✓ IP validation passed: {new_ip}")

    # Step 2: Read current file
    try:
        with open(params_file, 'r', encoding='utf-8') as f:
            original_content = f.read()
    except FileNotFoundError:
        error = f'params.py not found at {params_file}'
        logger.error(f"[GCS Config] {error}")
        return {'success': False, 'error': error}
    except Exception as e:
        error = f'Error reading params.py: {e}'
        logger.error(f"[GCS Config] {error}")
        return {'success': False, 'error': error}

    # Step 3: Extract current IP for logging
    old_ip_match = re.search(r'GCS_IP\s*=\s*"([^"]+)"', original_content)
    old_ip = old_ip_match.group(1) if old_ip_match else 'unknown'

    logger.info(f"[GCS Config] Current GCS IP: {old_ip}")

    # Check if IP is actually changing
    if old_ip == new_ip:
        logger.info(f"[GCS Config] No change needed - IP already set to {new_ip}")
        return {
            'success': True,
            'old_ip': old_ip,
            'new_ip': new_ip,
            'file_path': params_file,
            'no_change': True
        }

    # Step 4: Replace GCS_IP line using regex
    # Pattern matches: GCS_IP = "anything_here"
    # Preserves surrounding whitespace and comment structure
    pattern = r'(GCS_IP\s*=\s*")[^"]+(")'
    replacement = f'\\1{new_ip}\\2'
    new_content, count = re.subn(pattern, replacement, original_content)

    if count != 1:
        error = f'Unexpected number of GCS_IP matches in file: {count} (expected 1)'
        logger.error(f"[GCS Config] {error}")
        return {'success': False, 'error': error}

    logger.info(f"[GCS Config] ✓ Regex replacement successful")

    # Step 5: Validate Python syntax before writing
    try:
        compile(new_content, params_file, 'exec')
        logger.info(f"[GCS Config] ✓ Python syntax validation passed")
    except SyntaxError as e:
        error = f'Syntax error would be introduced: {e}'
        logger.error(f"[GCS Config] {error}")
        return {'success': False, 'error': error}

    # Step 6: Write updated file
    try:
        with open(params_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        logger.info(f"[GCS Config] ✅ File written successfully")
        logger.info(f"[GCS Config] ✅ GCS IP updated: {old_ip} → {new_ip}")
    except Exception as e:
        error = f'Error writing file: {e}'
        logger.error(f"[GCS Config] {error}")
        return {'success': False, 'error': error}

    return {
        'success': True,
        'old_ip': old_ip,
        'new_ip': new_ip,
        'file_path': params_file
    }


def get_current_gcs_ip():
    """
    Read current GCS_IP from params.py without importing
    (to avoid import side effects)

    Returns:
        str or None: Current GCS IP or None if not found
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params_file = os.path.join(base_dir, 'src', 'params.py')

    try:
        with open(params_file, 'r', encoding='utf-8') as f:
            content = f.read()

        match = re.search(r'GCS_IP\s*=\s*"([^"]+)"', content)
        return match.group(1) if match else None
    except Exception as e:
        logger.error(f"[GCS Config] Error reading current GCS IP: {e}")
        return None
