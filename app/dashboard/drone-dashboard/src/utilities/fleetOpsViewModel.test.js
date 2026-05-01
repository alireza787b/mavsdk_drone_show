import {
  buildFleetOpsViewModel,
  buildGitHubDocsUrl,
  classifyNodePresence,
  classifyGitSyncRuntime,
  classifyMavlinkRuntime,
  compactHash,
} from './fleetOpsViewModel';

describe('fleetOpsViewModel', () => {
  test('builds fleet rows and compliance counters from git status and heartbeat payloads', () => {
    const gitPayload = {
      gcs_status: {
        branch: 'main',
        commit: 'abcdef123456',
        remote_url: 'git@github.com:demo/customer-mds.git',
      },
      git_status: {
        1: {
          pos_id: 1,
          hw_id: '1',
          ip: '100.82.72.33',
          branch: 'main',
          commit: 'abcdef123456',
          in_sync_with_gcs: true,
          repo_access_mode: 'https_token_file',
          git_auth_health_status: 'healthy',
          git_auth_health_summary: 'HTTPS token-file access is configured and readable.',
          mavlink_runtime: {
            management_mode: 'managed',
            ref: 'v3.0.8',
            router_service_status: 'active',
            dashboard_service_status: 'active',
            dashboard_access_mode: 'local_only',
            desired_config_hash: 'abcdef1234567890abcdef',
            applied_config_hash: 'abcdef1234567890abcdef',
            config_hash_match: true,
          },
          connectivity_runtime: {
            backend: 'none',
            service_status: 'unknown',
            mode: 'observe',
            profile_present: false,
          },
        },
        2: {
          pos_id: 2,
          hw_id: '2',
          ip: '100.82.47.7',
          branch: 'main',
          commit: '1111111',
          in_sync_with_gcs: false,
          repo_access_mode: 'ssh_key',
          git_auth_health_status: 'warning',
          git_auth_health_summary: 'SSH key is missing.',
        },
      },
    };
    const heartbeatPayload = {
      heartbeats: [
        { pos_id: 1, hw_id: '1', ip: '100.82.72.33', online: true, runtime_mode: 'real' },
        { pos_id: 2, hw_id: '2', ip: '100.82.47.7', online: false, runtime_mode: 'real' },
      ],
    };

    const viewModel = buildFleetOpsViewModel(gitPayload, heartbeatPayload);

    expect(viewModel.rows).toHaveLength(2);
    expect(viewModel.summary).toMatchObject({
      total: 2,
      online: 1,
      stale: 0,
      offline: 1,
      synced: 1,
      authHealthy: 1,
      mavlinkHealthy: 1,
      connectivityNotApplicable: 1,
      sidecarAttention: 0,
      nodeSyncRuntimeAttention: 0,
      needsAttention: 1,
    });
    expect(viewModel.rows[0]).toMatchObject({
      posId: '1',
      runtimeModeLabel: 'REAL',
      accessLabel: 'HTTPS token',
      needsAttention: false,
    });
    expect(viewModel.docs.fleetOps).toBe('https://github.com/demo/customer-mds/blob/main/docs/guides/fleet-ops.md');
    expect(viewModel.rows[1]).toMatchObject({
      posId: '2',
      needsAttention: true,
      hasDrift: true,
      sync: expect.objectContaining({ state: 'drifted' }),
      auth: expect.objectContaining({ tone: 'warning' }),
    });
  });

  test('marks managed mavlink-anywhere as not applicable for SITL nodes', () => {
    expect(classifyMavlinkRuntime({ router_service_status: 'active' }, 'sitl')).toMatchObject({
      state: 'not_applicable',
      tone: 'muted',
    });
  });

  test('marks managed sidecar hash drift as operator attention', () => {
    expect(classifyMavlinkRuntime({
      management_mode: 'managed',
      router_service_status: 'active',
      dashboard_enabled: false,
      desired_config_hash: 'ffffffffffffffff',
      applied_config_hash: 'eeeeeeeeeeeeeeee',
      config_hash_match: false,
    }, 'real')).toMatchObject({
      state: 'drifted',
      label: 'Drift',
      tone: 'warning',
    });
  });

  test('marks node-local git sync runtime warnings as operator attention', () => {
    expect(classifyGitSyncRuntime({
      status: 'success',
      summary: 'Git synchronization completed successfully; unit update requires installer refresh.',
      service_reload_status: 'warning',
      deferred_unit_actions: ['git_sync_mds.service:manual_unit_update_required'],
      mavlink_runtime_reconcile_status: 'success',
      connectivity_reconcile_status: 'not_required',
    })).toMatchObject({
      state: 'attention',
      label: 'Attention',
      tone: 'warning',
    });
  });

  test('does not treat not-required runtime steps as warnings', () => {
    expect(classifyGitSyncRuntime({
      status: 'success',
      summary: 'Git synchronization completed successfully.',
      service_reload_status: 'not_required',
      mavlink_runtime_reconcile_status: 'success',
      connectivity_reconcile_status: 'not_required',
    })).toMatchObject({
      state: 'healthy',
      tone: 'good',
    });
  });

  test('does not treat SITL systemd reconcile skip as operator attention', () => {
    expect(classifyGitSyncRuntime({
      status: 'success',
      summary: 'Git synchronization completed successfully.',
      service_reload_status: 'skipped',
      service_reload_message: 'Systemd unit reconcile skipped for this runtime.',
      mavlink_runtime_reconcile_status: 'not_required',
      connectivity_reconcile_status: 'not_required',
    })).toMatchObject({
      state: 'healthy',
      tone: 'good',
    });
  });

  test('does not treat unknown-only git sync runtime state as attention', () => {
    expect(classifyGitSyncRuntime({
      status: 'unknown',
      summary: 'No node-local git sync runtime state has been recorded yet.',
      mavlink_runtime_reconcile_status: 'unknown',
      connectivity_reconcile_status: 'unknown',
    })).toMatchObject({
      state: 'unknown',
      tone: 'muted',
    });
  });

  test('compacts sidecar hashes for fleet display', () => {
    expect(compactHash('abcdef1234567890')).toBe('abcdef123456');
    expect(compactHash('')).toBe('unknown');
  });

  test('builds safe GitHub docs URLs only from normal GitHub remotes', () => {
    expect(buildGitHubDocsUrl('https://github.com/demo/customer-mds.git', 'main', '/docs/guides/fleet-ops.md'))
      .toBe('https://github.com/demo/customer-mds/blob/main/docs/guides/fleet-ops.md');
    expect(buildGitHubDocsUrl('git@github.com:demo/customer-mds.git', 'main', 'docs/guides/fleet-ops.md'))
      .toBe('https://github.com/demo/customer-mds/blob/main/docs/guides/fleet-ops.md');
    expect(buildGitHubDocsUrl('https://token@github.com/demo/customer-mds.git', 'main', 'docs/guides/fleet-ops.md'))
      .toBeNull();
  });

  test('separates never-seen, recent-loss, stale, and offline node presence', () => {
    expect(classifyNodePresence(null, 100000)).toMatchObject({
      state: 'never_seen',
      tone: 'muted',
    });
    expect(classifyNodePresence({ online: false, runtime_mode: 'real', last_heartbeat: 90000 }, 100000)).toMatchObject({
      state: 'recently_lost',
      tone: 'warning',
    });
    expect(classifyNodePresence({ online: false, runtime_mode: 'real', last_heartbeat: 50000 }, 100000)).toMatchObject({
      state: 'stale',
      tone: 'warning',
    });
    expect(classifyNodePresence({ online: false, runtime_mode: 'real', last_heartbeat: 1000 }, 100000)).toMatchObject({
      state: 'offline',
      tone: 'danger',
    });
  });

  test('uses canonical backend presence snapshots when available', () => {
    expect(classifyNodePresence({
      online: false,
      presence_state: 'stale',
      presence: {
        state: 'stale',
        source: 'heartbeat',
        age_sec: 44.2,
        detail: 'Link stale for 44.2s.',
      },
    }, 100000)).toMatchObject({
      state: 'stale',
      label: 'Stale',
      tone: 'warning',
      source: 'heartbeat',
    });
  });
});
