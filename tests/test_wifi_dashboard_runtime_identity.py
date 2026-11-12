"""Reconcile verifies the installed dashboard, not only its source tag."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('initial_match,offline,broken_install,expected', [
    (True, False, False, 0), (False, False, False, 0),
    (False, True, False, 1), (False, False, True, 1),
])
def test_dashboard_identity_controls_skip_repair_and_success(tmp_path, initial_match, offline, broken_install, expected):
    repo, sidecar, fakebin = (tmp_path/name for name in ('repo', 'sidecar', 'bin'))
    for path in (repo/'tools', repo/'deployment', sidecar/'.git', sidecar/'scripts', fakebin):
        path.mkdir(parents=True)
    for name in ('reconcile_connectivity.sh', 'load_deployment_profile.sh'):
        shutil.copy2(ROOT/'tools'/name, repo/'tools'/name)
    (repo/'deployment/defaults.env').write_text('MDS_DEFAULT_SMART_WIFI_MANAGER_REF=v9.9.9\n')
    local = tmp_path/'local.env'
    local.write_text(f'MDS_CONNECTIVITY_BACKEND=smart-wifi-manager\nMDS_SMART_WIFI_MANAGER_INSTALL_DIR={sidecar}\nMDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:19080\n')
    scripts = {
        fakebin/'git': '''#!/bin/bash
printf '%s\n' "$*" >> "$TMPDIR/git-calls"
case "$*" in
  *'describe --tags --exact-match HEAD'*) echo v9.9.9;;
  *'fetch --depth 1'*) test "$TEST_OFFLINE" != 1;;
esac
''',
        fakebin/'systemctl': '#!/bin/sh\nexit 0\n',
        sidecar/'scripts/check_dashboard_version.sh': '''#!/bin/bash
test "$SMART_WIFI_MANAGER_DASHBOARD_URL" = http://127.0.0.1:19080/api/meta || exit 9
test "$SMART_WIFI_MANAGER_DASHBOARD_BINARY" = "$TEST_SIDECAR/build/smart-wifi-manager-dashboard" || exit 9
test "$TEST_BROKEN_INSTALL" != 1 || exit 2
test "$TEST_INITIAL_MATCH" = 1 || test -f "$TMPDIR/installed"
''',
        sidecar/'install.sh': '#!/bin/sh\ntouch "$TMPDIR/installed"\n',
        sidecar/'configure_smart_wifi_manager.sh': '#!/bin/sh\ntouch "$TMPDIR/configured"\n',
    }
    for path, text in scripts.items():
        path.write_text(text)
        path.chmod(0o755)
    env = {**os.environ, 'PATH':str(fakebin)+os.pathsep+os.environ['PATH'],
        'TMPDIR':str(tmp_path), 'MDS_LOCAL_ENV_FILE':str(local),
        'MDS_CONNECTIVITY_STATE_DIR':str(tmp_path/'state'),
        'TEST_SIDECAR':str(sidecar),'TEST_INITIAL_MATCH':str(int(initial_match)),
        'TEST_OFFLINE':str(int(offline)), 'TEST_BROKEN_INSTALL':str(int(broken_install))}
    env.pop('MDS_MODE', None)
    command = ['bash',str(repo/'tools/reconcile_connectivity.sh'),'apply','--force']
    result = subprocess.run(command,env=env,capture_output=True,text=True,timeout=15)
    assert (result.returncode != 0) == bool(expected), result.stdout+result.stderr
    assert (tmp_path/'configured').exists() == (expected == 0)
    assert (tmp_path/'state/smart_wifi_manager_profile.sha256').exists() == (expected == 0)
    if initial_match:
        assert not (tmp_path/'installed').exists()
    elif not offline:
        assert (tmp_path/'installed').exists()
    fetches = [line for line in (tmp_path/'git-calls').read_text().splitlines() if 'fetch --depth 1' in line]
    assert all('fetch --depth 1 --tags origin' in line for line in fetches)
    if expected == 0:
        # An unchanged policy may skip only while actual dashboard identity matches.
        (tmp_path/'installed').unlink(missing_ok=True)
        env['TEST_INITIAL_MATCH'] = '0'
        again = subprocess.run(command[:-1],env=env,capture_output=True,text=True,timeout=15)
        assert again.returncode == 0, again.stdout+again.stderr
        assert (tmp_path/'installed').exists()
