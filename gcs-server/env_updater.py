"""
Dashboard .env File Updater
Updates REACT_APP_SERVER_URL in dashboard .env file
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

def update_dashboard_env(new_gcs_ip):
    """
    Update REACT_APP_SERVER_URL in dashboard .env file

    Args:
        new_gcs_ip (str): New GCS IP address

    Returns:
        dict: {'success': bool, 'old_url': str, 'new_url': str, 'error': str}
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_file = os.path.join(base_dir, 'app', 'dashboard', 'drone-dashboard', '.env')

    new_url = f'http://{new_gcs_ip}'

    # Read current file
    try:
        if not os.path.exists(env_file):
            # Create file if doesn't exist
            with open(env_file, 'w', encoding='utf-8') as f:
                f.write(f'REACT_APP_SERVER_URL={new_url}\n')
                f.write('REACT_APP_GCS_PORT=5000\n')
            return {
                'success': True,
                'old_url': None,
                'new_url': new_url,
                'created': True
            }

        with open(env_file, 'r', encoding='utf-8') as f:
            original_content = f.read()
    except Exception as e:
        return {'success': False, 'error': f'Error reading .env file: {e}'}

    # Extract current URL
    old_url_match = re.search(r'REACT_APP_SERVER_URL=(.+)', original_content)
    old_url = old_url_match.group(1).strip() if old_url_match else None

    # Check if already set
    if old_url == new_url:
        return {
            'success': True,
            'old_url': old_url,
            'new_url': new_url,
            'no_change': True
        }

    # Replace URL
    pattern = r'(REACT_APP_SERVER_URL=)(.+)'
    replacement = f'\\1{new_url}'
    new_content, count = re.subn(pattern, replacement, original_content)

    # If pattern not found, append it
    if count == 0:
        new_content = original_content.rstrip() + f'\nREACT_APP_SERVER_URL={new_url}\n'

    # Write updated file
    try:
        with open(env_file, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return {
            'success': True,
            'old_url': old_url,
            'new_url': new_url
        }
    except Exception as e:
        return {'success': False, 'error': f'Error writing .env file: {e}'}
