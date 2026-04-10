import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { toast } from 'react-toastify';
import {
  FaArrowRight,
  FaBan,
  FaCheckCircle,
  FaExclamationTriangle,
  FaPauseCircle,
  FaPlus,
  FaRedoAlt,
  FaSatelliteDish,
  FaSyncAlt,
} from 'react-icons/fa';
import useFetch from '../hooks/useFetch';
import {
  acceptFleetCandidate,
  ignoreFleetCandidate,
  recoverFleetCandidate,
  rejectFleetCandidate,
  replaceFleetCandidate,
} from '../services/fleetEnrollmentApiService';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import {
  compareMissionIds,
  formatDroneLabel,
  formatShowSlotLabel,
  normalizeComparableId,
  normalizeDroneConfigData,
} from '../utilities/missionIdentityUtils';
import '../styles/FleetEnrollmentPage.css';

const ACTIVE_STATE_SET = new Set(['pending_operator_review', 'conflict']);

function formatCandidateStateLabel(state) {
  switch (state) {
    case 'pending_operator_review':
      return 'Pending review';
    case 'conflict':
      return 'Conflict';
    case 'accepted':
      return 'Accepted';
    case 'rejected':
      return 'Rejected';
    case 'ignored':
      return 'Ignored';
    case 'superseded':
      return 'Superseded';
    default:
      return 'Unknown';
  }
}

function formatCandidateStateTone(state) {
  switch (state) {
    case 'conflict':
      return 'warning';
    case 'accepted':
      return 'good';
    case 'rejected':
      return 'danger';
    case 'ignored':
    case 'superseded':
      return 'muted';
    case 'pending_operator_review':
    default:
      return 'info';
  }
}

function formatConflictReason(reason) {
  switch (reason) {
    case 'hw_id_already_in_fleet':
      return 'Hardware ID already exists in fleet config';
    case 'ip_already_in_fleet':
      return 'Control-plane IP already exists in fleet config';
    case 'duplicate_candidate_hw_id':
      return 'Another active candidate is using the same hardware ID';
    case 'missing_identity':
      return 'Candidate is missing a stable node identity';
    default:
      return String(reason || 'Unknown conflict');
  }
}

function formatHeartbeatSummary(candidate) {
  if (!candidate) {
    return 'Unknown';
  }
  const label = candidate.heartbeat_status
    ? formatCandidateStateLabel(candidate.heartbeat_status).replace(/^./, (value) => value.toUpperCase())
    : 'Unknown';
  if (candidate.heartbeat_age_sec === null || candidate.heartbeat_age_sec === undefined) {
    return label;
  }
  return `${label} · ${candidate.heartbeat_age_sec}s`;
}

function buildCandidateSearchBlob(candidate) {
  return [
    candidate.candidate_id,
    candidate.hw_id,
    candidate.hostname,
    candidate.node_uuid,
    candidate.primary_control_ip,
    ...(candidate.ip_addresses || []),
    candidate.reported_pos_id,
    candidate.detected_pos_id,
    candidate.registration_state,
    ...(candidate.conflict_reasons || []),
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

function filterCandidateByState(candidate, stateFilter) {
  if (stateFilter === 'all') {
    return true;
  }
  if (stateFilter === 'active') {
    return ACTIVE_STATE_SET.has(candidate.registration_state);
  }
  return candidate.registration_state === stateFilter;
}

function buildMutationNotice(responseData) {
  if (!responseData) {
    return null;
  }

  const warnings = Array.isArray(responseData.warnings) ? responseData.warnings : [];
  return {
    tone: warnings.length > 0 ? 'warning' : 'success',
    title: responseData.message || 'Enrollment update completed',
    detail: warnings.length > 0 ? warnings.join(' · ') : '',
  };
}

function EnrollmentNotice({ notice }) {
  if (!notice) {
    return null;
  }

  return (
    <div className={`fleet-enrollment-notice fleet-enrollment-notice--${notice.tone || 'info'}`}>
      <strong>{notice.title}</strong>
      {notice.detail ? <span>{notice.detail}</span> : null}
    </div>
  );
}

function CandidateStatePill({ state }) {
  return (
    <span className={`fleet-enrollment-state-pill fleet-enrollment-state-pill--${formatCandidateStateTone(state)}`}>
      {formatCandidateStateLabel(state)}
    </span>
  );
}

function ActionDialog({
  isOpen,
  title,
  description,
  busy,
  onClose,
  onSubmit,
  submitLabel,
  tone = 'default',
  children,
}) {
  if (!isOpen) {
    return null;
  }

  return (
    <div className="fleet-enrollment-dialog-backdrop" onClick={busy ? undefined : onClose}>
      <div
        className={`fleet-enrollment-dialog fleet-enrollment-dialog--${tone}`}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="fleet-enrollment-dialog__header">
          <div>
            <h2>{title}</h2>
            {description ? <p>{description}</p> : null}
          </div>
          <button type="button" className="fleet-enrollment-dialog__close" onClick={onClose} disabled={busy}>
            Close
          </button>
        </div>
        <div className="fleet-enrollment-dialog__body">
          {children}
        </div>
        <div className="fleet-enrollment-dialog__actions">
          <button type="button" className="fleet-enrollment-button fleet-enrollment-button--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="fleet-enrollment-button fleet-enrollment-button--primary" onClick={onSubmit} disabled={busy}>
            {busy ? 'Working…' : submitLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function FleetEnrollmentPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [refreshTick, setRefreshTick] = useState(0);
  const [searchQuery, setSearchQuery] = useState('');
  const [stateFilter, setStateFilter] = useState('active');
  const [selectedCandidateId, setSelectedCandidateId] = useState(null);
  const [dialogMode, setDialogMode] = useState(null);
  const [dialogState, setDialogState] = useState({});
  const [mutationNotice, setMutationNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  const requestedCandidateId = searchParams.get('candidate');
  const requestedReplaceTarget = normalizeComparableId(searchParams.get('replace'));

  const candidateEndpoint = useMemo(
    () => `${GCS_ROUTE_KEYS.fleetCandidates}?include_inactive=true&_=${refreshTick}`,
    [refreshTick]
  );
  const { data: candidateResponse, loading: candidateLoading, error: candidateError } = useFetch(candidateEndpoint, 5000);
  const { data: fleetConfigResponse } = useFetch(GCS_ROUTE_KEYS.fleetConfig, 10000);

  const configData = useMemo(() => (
    Array.isArray(fleetConfigResponse) ? normalizeDroneConfigData(fleetConfigResponse) : []
  ), [fleetConfigResponse]);

  const allCandidates = useMemo(() => (
    Array.isArray(candidateResponse?.candidates) ? candidateResponse.candidates : []
  ), [candidateResponse]);

  const filteredCandidates = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return allCandidates
      .filter((candidate) => filterCandidateByState(candidate, stateFilter))
      .filter((candidate) => !normalizedQuery || buildCandidateSearchBlob(candidate).includes(normalizedQuery))
      .sort((left, right) => {
        const stateOrder = {
          conflict: 0,
          pending_operator_review: 1,
          accepted: 2,
          ignored: 3,
          rejected: 4,
          superseded: 5,
        };
        const stateDelta = (stateOrder[left.registration_state] ?? 99) - (stateOrder[right.registration_state] ?? 99);
        if (stateDelta !== 0) {
          return stateDelta;
        }
        return compareMissionIds(left.hw_id, right.hw_id);
      });
  }, [allCandidates, searchQuery, stateFilter]);

  useEffect(() => {
    if (requestedCandidateId && allCandidates.some((candidate) => candidate.candidate_id === requestedCandidateId)) {
      setSelectedCandidateId(requestedCandidateId);
      return;
    }

    if (selectedCandidateId && filteredCandidates.some((candidate) => candidate.candidate_id === selectedCandidateId)) {
      return;
    }

    setSelectedCandidateId(filteredCandidates[0]?.candidate_id || null);
  }, [allCandidates, filteredCandidates, requestedCandidateId, selectedCandidateId]);

  const selectedCandidate = useMemo(
    () => allCandidates.find((candidate) => candidate.candidate_id === selectedCandidateId) || null,
    [allCandidates, selectedCandidateId]
  );

  const matchingConfiguredDrone = useMemo(() => (
    selectedCandidate
      ? configData.find((drone) => normalizeComparableId(drone.hw_id) === normalizeComparableId(selectedCandidate.hw_id)) || null
      : null
  ), [configData, selectedCandidate]);

  const replacementTargetDrone = useMemo(() => (
    requestedReplaceTarget
      ? configData.find((drone) => normalizeComparableId(drone.hw_id) === requestedReplaceTarget) || null
      : null
  ), [configData, requestedReplaceTarget]);

  const candidateCounts = useMemo(() => {
    const counts = {
      active: 0,
      pending_operator_review: 0,
      conflict: 0,
      accepted: 0,
      ignored: 0,
      rejected: 0,
      superseded: 0,
    };
    allCandidates.forEach((candidate) => {
      if (ACTIVE_STATE_SET.has(candidate.registration_state)) {
        counts.active += 1;
      }
      counts[candidate.registration_state] = (counts[candidate.registration_state] || 0) + 1;
    });
    return counts;
  }, [allCandidates]);

  const openDialog = (mode) => {
    if (!selectedCandidate) {
      return;
    }

    if (mode === 'accept') {
      setDialogState({
        pos_id: selectedCandidate.reported_pos_id || selectedCandidate.detected_pos_id || '',
        ip: selectedCandidate.primary_control_ip || '',
        mavlink_port: 14550,
        serial_port: '',
        baudrate: 0,
        color: '',
        notes: '',
        commit: true,
      });
    } else if (mode === 'replace') {
      setDialogState({
        target_hw_id: requestedReplaceTarget || '',
        ip: selectedCandidate.primary_control_ip || '',
        mavlink_port: '',
        serial_port: '',
        baudrate: '',
        notes: '',
        commit: true,
      });
    } else if (mode === 'recover') {
      setDialogState({
        ip: selectedCandidate.primary_control_ip || matchingConfiguredDrone?.ip || '',
        mavlink_port: matchingConfiguredDrone?.mavlink_port ?? '',
        serial_port: matchingConfiguredDrone?.serial_port ?? '',
        baudrate: matchingConfiguredDrone?.baudrate ?? '',
        notes: '',
        commit: true,
      });
    } else {
      setDialogState({ reason: '' });
    }

    setDialogMode(mode);
  };

  const closeDialog = () => {
    if (busy) {
      return;
    }
    setDialogMode(null);
    setDialogState({});
  };

  const updateDialogState = (field, value) => {
    setDialogState((current) => ({ ...current, [field]: value }));
  };

  const normalizeOptionalString = (value) => {
    const normalized = typeof value === 'string' ? value.trim() : value;
    return normalized === '' ? undefined : normalized;
  };

  const normalizeOptionalInteger = (value) => {
    if (value === '' || value === null || value === undefined) {
      return undefined;
    }
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : undefined;
  };

  const handleMutation = async () => {
    if (!selectedCandidate || !dialogMode) {
      return;
    }

    setBusy(true);
    setMutationNotice(null);

    try {
      let response;

      if (dialogMode === 'accept') {
        response = await acceptFleetCandidate(
          selectedCandidate.candidate_id,
          {
            pos_id: Number(dialogState.pos_id),
            ip: normalizeOptionalString(dialogState.ip),
            mavlink_port: Number(dialogState.mavlink_port),
            serial_port: dialogState.serial_port || '',
            baudrate: Number(dialogState.baudrate || 0),
            color: normalizeOptionalString(dialogState.color),
            notes: normalizeOptionalString(dialogState.notes),
          },
          { commit: Boolean(dialogState.commit) },
        );
      } else if (dialogMode === 'replace') {
        response = await replaceFleetCandidate(
          selectedCandidate.candidate_id,
          {
            target_hw_id: Number(dialogState.target_hw_id),
            ip: normalizeOptionalString(dialogState.ip),
            mavlink_port: normalizeOptionalInteger(dialogState.mavlink_port),
            serial_port: normalizeOptionalString(dialogState.serial_port),
            baudrate: normalizeOptionalInteger(dialogState.baudrate),
            notes: normalizeOptionalString(dialogState.notes),
          },
          { commit: Boolean(dialogState.commit) },
        );
      } else if (dialogMode === 'recover') {
        response = await recoverFleetCandidate(
          selectedCandidate.candidate_id,
          {
            ip: normalizeOptionalString(dialogState.ip),
            mavlink_port: normalizeOptionalInteger(dialogState.mavlink_port),
            serial_port: normalizeOptionalString(dialogState.serial_port),
            baudrate: normalizeOptionalInteger(dialogState.baudrate),
            notes: normalizeOptionalString(dialogState.notes),
          },
          { commit: Boolean(dialogState.commit) },
        );
      } else if (dialogMode === 'ignore') {
        response = await ignoreFleetCandidate(selectedCandidate.candidate_id, {
          reason: normalizeOptionalString(dialogState.reason),
        });
      } else {
        response = await rejectFleetCandidate(selectedCandidate.candidate_id, {
          reason: normalizeOptionalString(dialogState.reason),
        });
      }

      const responseData = response.data;
      setMutationNotice(buildMutationNotice(responseData));
      toast.success(responseData.message || 'Enrollment action completed.');
      setRefreshTick((value) => value + 1);
      closeDialog();
      if (requestedReplaceTarget) {
        const nextParams = new URLSearchParams(searchParams);
        nextParams.delete('replace');
        setSearchParams(nextParams, { replace: true });
      }
    } catch (error) {
      const detail = error?.response?.data?.detail || error?.message || 'Enrollment action failed.';
      setMutationNotice({
        tone: 'danger',
        title: 'Enrollment action failed',
        detail,
      });
      toast.error(detail);
    } finally {
      setBusy(false);
    }
  };

  const canAcceptAsNew = selectedCandidate
    && normalizeComparableId(selectedCandidate.hw_id)
    && !matchingConfiguredDrone;
  const canRecoverExisting = Boolean(selectedCandidate && matchingConfiguredDrone);
  const canReplaceExisting = Boolean(selectedCandidate && configData.length > 0 && !matchingConfiguredDrone);

  return (
    <div className="fleet-enrollment-page">
      <header className="fleet-enrollment-page__header">
        <div className="fleet-enrollment-page__copy">
          <span className="fleet-enrollment-page__kicker">Node Enrollment</span>
          <h1>Fleet Enrollment</h1>
          <p>
            Review newly discovered nodes, accept them into the fleet, replace a failed slot with a spare,
            or recover the same hardware ID after a companion-computer rebuild.
          </p>
        </div>
        <div className="fleet-enrollment-page__actions">
          <button
            type="button"
            className="fleet-enrollment-button fleet-enrollment-button--ghost"
            onClick={() => setRefreshTick((value) => value + 1)}
          >
            <FaSyncAlt />
            Refresh
          </button>
          <Link className="fleet-enrollment-button fleet-enrollment-button--ghost" to="/mission-config">
            Mission Config
          </Link>
        </div>
      </header>

      <div className="fleet-enrollment-summary-grid">
        <article className="fleet-enrollment-summary-card">
          <span>Active review queue</span>
          <strong>{candidateCounts.active}</strong>
          <small>Pending or conflict candidates waiting on an operator decision.</small>
        </article>
        <article className="fleet-enrollment-summary-card">
          <span>Conflict candidates</span>
          <strong>{candidateCounts.conflict}</strong>
          <small>Conflicts usually mean duplicate hardware ID, duplicate IP, or incomplete identity.</small>
        </article>
        <article className="fleet-enrollment-summary-card">
          <span>Accepted history</span>
          <strong>{candidateCounts.accepted}</strong>
          <small>Recovered, replaced, or newly accepted nodes already resolved by GCS.</small>
        </article>
      </div>

      {requestedReplaceTarget && replacementTargetDrone ? (
        <div className="fleet-enrollment-banner">
          <FaArrowRight />
          <div>
            <strong>Replacement workflow armed for {formatDroneLabel(replacementTargetDrone.hw_id)}</strong>
            <span>
              Select a pending spare candidate, then use <strong>Replace existing slot</strong> to preserve
              {` ${formatShowSlotLabel(replacementTargetDrone.pos_id)}`}.
            </span>
          </div>
        </div>
      ) : null}

      <EnrollmentNotice notice={mutationNotice} />

      <section className="fleet-enrollment-toolbar" aria-label="Fleet enrollment filters">
        <label className="fleet-enrollment-toolbar__search">
          <span>Search candidates</span>
          <input
            type="search"
            value={searchQuery}
            onChange={(event) => setSearchQuery(event.target.value)}
            placeholder="Search by H, hostname, IP, node UUID, or conflict"
          />
        </label>
        <label className="fleet-enrollment-toolbar__filter">
          <span>Filter</span>
          <select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}>
            <option value="active">Active review queue</option>
            <option value="pending_operator_review">Pending only</option>
            <option value="conflict">Conflicts only</option>
            <option value="accepted">Accepted only</option>
            <option value="ignored">Ignored only</option>
            <option value="rejected">Rejected only</option>
            <option value="all">All candidates</option>
          </select>
        </label>
      </section>

      <div className="fleet-enrollment-layout">
        <section className="fleet-enrollment-list" aria-label="Fleet candidates">
          {candidateLoading ? (
            <div className="fleet-enrollment-empty-state">Loading fleet candidates…</div>
          ) : candidateError ? (
            <div className="fleet-enrollment-empty-state fleet-enrollment-empty-state--danger">
              Fleet candidate state could not be loaded.
            </div>
          ) : filteredCandidates.length === 0 ? (
            <div className="fleet-enrollment-empty-state">
              No candidates match the current filters.
            </div>
          ) : (
            filteredCandidates.map((candidate) => {
              const isSelected = candidate.candidate_id === selectedCandidateId;
              const slotHint = candidate.reported_pos_id
                ? `${formatShowSlotLabel(candidate.reported_pos_id)} reported`
                : candidate.detected_pos_id
                  ? `${formatShowSlotLabel(candidate.detected_pos_id)} detected`
                  : 'No slot hint';

              return (
                <button
                  key={candidate.candidate_id}
                  type="button"
                  className={`fleet-enrollment-candidate-card ${isSelected ? 'active' : ''}`}
                  onClick={() => {
                    setSelectedCandidateId(candidate.candidate_id);
                    const nextParams = new URLSearchParams(searchParams);
                    nextParams.set('candidate', candidate.candidate_id);
                    setSearchParams(nextParams, { replace: true });
                  }}
                >
                  <div className="fleet-enrollment-candidate-card__header">
                    <div>
                      <strong>{formatDroneLabel(candidate.hw_id || '—')}</strong>
                      <span>{candidate.hostname || candidate.candidate_id}</span>
                    </div>
                    <CandidateStatePill state={candidate.registration_state} />
                  </div>
                  <div className="fleet-enrollment-candidate-card__meta">
                    <span>{slotHint}</span>
                    <span>{candidate.primary_control_ip || candidate.ip_addresses?.[0] || 'IP pending'}</span>
                    <span>{formatHeartbeatSummary(candidate)}</span>
                  </div>
                  {candidate.conflict_reasons?.length ? (
                    <div className="fleet-enrollment-candidate-card__warnings">
                      <FaExclamationTriangle />
                      <span>{candidate.conflict_reasons.map(formatConflictReason).join(' · ')}</span>
                    </div>
                  ) : null}
                </button>
              );
            })
          )}
        </section>

        <aside className="fleet-enrollment-inspector" aria-label="Candidate review inspector">
          {selectedCandidate ? (
            <>
              <div className="fleet-enrollment-inspector__identity">
                <div>
                  <span className="fleet-enrollment-page__kicker">Selected candidate</span>
                  <h2>{formatDroneLabel(selectedCandidate.hw_id || '—')}</h2>
                  <p>{selectedCandidate.hostname || selectedCandidate.candidate_id}</p>
                </div>
                <CandidateStatePill state={selectedCandidate.registration_state} />
              </div>

              <div className="fleet-enrollment-inspector__grid">
                <section className="fleet-enrollment-panel">
                  <h3>Identity</h3>
                  <dl>
                    <div><dt>Candidate ID</dt><dd>{selectedCandidate.candidate_id}</dd></div>
                    <div><dt>Node UUID</dt><dd>{selectedCandidate.node_uuid || '—'}</dd></div>
                    <div><dt>Hardware ID</dt><dd>{selectedCandidate.hw_id || '—'}</dd></div>
                    <div><dt>Slot hint</dt><dd>{selectedCandidate.reported_pos_id ? formatShowSlotLabel(selectedCandidate.reported_pos_id) : selectedCandidate.detected_pos_id ? `${formatShowSlotLabel(selectedCandidate.detected_pos_id)} detected` : '—'}</dd></div>
                  </dl>
                </section>

                <section className="fleet-enrollment-panel">
                  <h3>Bootstrap / network</h3>
                  <dl>
                    <div><dt>Hostname</dt><dd>{selectedCandidate.hostname || '—'}</dd></div>
                    <div><dt>Primary IP</dt><dd>{selectedCandidate.primary_control_ip || '—'}</dd></div>
                    <div><dt>Network mode</dt><dd>{selectedCandidate.network_mode || '—'}</dd></div>
                    <div><dt>Repo / branch</dt><dd>{selectedCandidate.repo_url ? `${selectedCandidate.repo_url} @ ${selectedCandidate.branch || 'unknown'}` : (selectedCandidate.branch || '—')}</dd></div>
                    <div><dt>Bootstrap status</dt><dd>{selectedCandidate.bootstrap_status || '—'}</dd></div>
                    <div><dt>MAVLink routing</dt><dd>{selectedCandidate.mavlink_routing_mode || '—'}</dd></div>
                  </dl>
                </section>

                <section className="fleet-enrollment-panel">
                  <h3>Operational guidance</h3>
                  {matchingConfiguredDrone ? (
                    <div className="fleet-enrollment-guidance fleet-enrollment-guidance--warning">
                      <FaSatelliteDish />
                      <div>
                        <strong>Same hardware ID already exists in fleet config.</strong>
                        <span>
                          Use <strong>Recover existing node</strong> when this is the same physical drone with a
                          rebuilt companion. Use <strong>Replace existing slot</strong> only when a different spare airframe
                          is taking over the slot.
                        </span>
                      </div>
                    </div>
                  ) : (
                    <div className="fleet-enrollment-guidance">
                      <FaCheckCircle />
                      <div>
                        <strong>This candidate can be accepted as a new fleet member.</strong>
                        <span>
                          Assign a position ID only after you decide which live slot or reserve role this node should own.
                        </span>
                      </div>
                    </div>
                  )}
                  {selectedCandidate.conflict_reasons?.length ? (
                    <ul className="fleet-enrollment-conflict-list">
                      {selectedCandidate.conflict_reasons.map((reason) => (
                        <li key={reason}>{formatConflictReason(reason)}</li>
                      ))}
                    </ul>
                  ) : null}
                </section>
              </div>

              <section className="fleet-enrollment-actions-panel">
                <div className="fleet-enrollment-actions-panel__header">
                  <h3>Available actions</h3>
                  <span>Choose the workflow that matches the real airframe situation.</span>
                </div>
                <div className="fleet-enrollment-actions-grid">
                  <button
                    type="button"
                    className="fleet-enrollment-action-card"
                    onClick={() => openDialog('accept')}
                    disabled={!canAcceptAsNew}
                  >
                    <FaPlus />
                    <strong>Add as new fleet member</strong>
                    <span>Assign a new slot and write this node into fleet config.</span>
                  </button>
                  <button
                    type="button"
                    className="fleet-enrollment-action-card"
                    onClick={() => openDialog('replace')}
                    disabled={!canReplaceExisting}
                  >
                    <FaArrowRight />
                    <strong>Replace existing slot</strong>
                    <span>Preserve the target slot while swapping in a different spare airframe.</span>
                  </button>
                  <button
                    type="button"
                    className="fleet-enrollment-action-card"
                    onClick={() => openDialog('recover')}
                    disabled={!canRecoverExisting}
                  >
                    <FaRedoAlt />
                    <strong>Recover existing node</strong>
                    <span>Same physical drone, same hardware ID, new companion or rebuilt image.</span>
                  </button>
                  <button
                    type="button"
                    className="fleet-enrollment-action-card fleet-enrollment-action-card--muted"
                    onClick={() => openDialog('ignore')}
                  >
                    <FaPauseCircle />
                    <strong>Ignore for now</strong>
                    <span>Keep the candidate visible in history without editing fleet config.</span>
                  </button>
                  <button
                    type="button"
                    className="fleet-enrollment-action-card fleet-enrollment-action-card--danger"
                    onClick={() => openDialog('reject')}
                  >
                    <FaBan />
                    <strong>Reject candidate</strong>
                    <span>Resolve this candidate as invalid, duplicate, or not part of the managed fleet.</span>
                  </button>
                </div>
              </section>
            </>
          ) : (
            <div className="fleet-enrollment-empty-state">Select a candidate to review its identity, conflicts, and actions.</div>
          )}
        </aside>
      </div>

      <ActionDialog
        isOpen={dialogMode === 'accept'}
        title="Add new fleet member"
        description="Assign this candidate to a new fleet slot."
        busy={busy}
        onClose={closeDialog}
        onSubmit={handleMutation}
        submitLabel="Accept as new member"
      >
        <div className="fleet-enrollment-form-grid">
          <label>
            <span>Position ID</span>
            <input type="number" min="1" value={dialogState.pos_id ?? ''} onChange={(event) => updateDialogState('pos_id', event.target.value)} />
          </label>
          <label>
            <span>Control-plane IP</span>
            <input type="text" value={dialogState.ip ?? ''} onChange={(event) => updateDialogState('ip', event.target.value)} />
          </label>
          <label>
            <span>MAVLink port</span>
            <input type="number" min="1" value={dialogState.mavlink_port ?? ''} onChange={(event) => updateDialogState('mavlink_port', event.target.value)} />
          </label>
          <label>
            <span>Serial port</span>
            <input type="text" value={dialogState.serial_port ?? ''} onChange={(event) => updateDialogState('serial_port', event.target.value)} placeholder="/dev/ttyAMA0 or blank for UDP" />
          </label>
          <label>
            <span>Baudrate</span>
            <input type="number" min="0" value={dialogState.baudrate ?? ''} onChange={(event) => updateDialogState('baudrate', event.target.value)} />
          </label>
          <label>
            <span>UI color</span>
            <input type="text" value={dialogState.color ?? ''} onChange={(event) => updateDialogState('color', event.target.value)} placeholder="#22c55e" />
          </label>
        </div>
        <label className="fleet-enrollment-form-stack">
          <span>Notes</span>
          <textarea rows="3" value={dialogState.notes ?? ''} onChange={(event) => updateDialogState('notes', event.target.value)} />
        </label>
        <label className="fleet-enrollment-checkbox">
          <input type="checkbox" checked={Boolean(dialogState.commit)} onChange={(event) => updateDialogState('commit', event.target.checked)} />
          <span>Commit and push repo changes after acceptance</span>
        </label>
      </ActionDialog>

      <ActionDialog
        isOpen={dialogMode === 'replace'}
        title="Replace existing slot"
        description="Preserve the chosen slot and swap this candidate into service."
        busy={busy}
        onClose={closeDialog}
        onSubmit={handleMutation}
        submitLabel="Replace slot"
      >
        <label className="fleet-enrollment-form-stack">
          <span>Target fleet member</span>
          <select value={dialogState.target_hw_id ?? ''} onChange={(event) => updateDialogState('target_hw_id', event.target.value)}>
            <option value="">Select the failed slot</option>
            {configData.map((drone) => (
              <option key={drone.hw_id} value={drone.hw_id}>
                {`${formatShowSlotLabel(drone.pos_id)} · ${formatDroneLabel(drone.hw_id)}`}
              </option>
            ))}
          </select>
        </label>
        <div className="fleet-enrollment-form-grid">
          <label>
            <span>Control-plane IP override</span>
            <input type="text" value={dialogState.ip ?? ''} onChange={(event) => updateDialogState('ip', event.target.value)} />
          </label>
          <label>
            <span>MAVLink port override</span>
            <input type="number" min="1" value={dialogState.mavlink_port ?? ''} onChange={(event) => updateDialogState('mavlink_port', event.target.value)} placeholder="Keep target value" />
          </label>
          <label>
            <span>Serial port override</span>
            <input type="text" value={dialogState.serial_port ?? ''} onChange={(event) => updateDialogState('serial_port', event.target.value)} placeholder="Keep target value" />
          </label>
          <label>
            <span>Baudrate override</span>
            <input type="number" min="0" value={dialogState.baudrate ?? ''} onChange={(event) => updateDialogState('baudrate', event.target.value)} placeholder="Keep target value" />
          </label>
        </div>
        <label className="fleet-enrollment-form-stack">
          <span>Notes</span>
          <textarea rows="3" value={dialogState.notes ?? ''} onChange={(event) => updateDialogState('notes', event.target.value)} />
        </label>
        <label className="fleet-enrollment-checkbox">
          <input type="checkbox" checked={Boolean(dialogState.commit)} onChange={(event) => updateDialogState('commit', event.target.checked)} />
          <span>Commit and push repo changes after replacement</span>
        </label>
      </ActionDialog>

      <ActionDialog
        isOpen={dialogMode === 'recover'}
        title="Recover existing node"
        description="Use this only when the same physical drone is returning with a rebuilt companion or fresh image."
        busy={busy}
        onClose={closeDialog}
        onSubmit={handleMutation}
        submitLabel="Recover node"
      >
        <div className="fleet-enrollment-guidance fleet-enrollment-guidance--subtle">
          <FaRedoAlt />
          <div>
            <strong>Recovering {matchingConfiguredDrone ? `${formatShowSlotLabel(matchingConfiguredDrone.pos_id)} · ${formatDroneLabel(matchingConfiguredDrone.hw_id)}` : formatDroneLabel(selectedCandidate?.hw_id)}</strong>
            <span>The fleet slot stays the same. Only companion/network transport details are updated.</span>
          </div>
        </div>
        <div className="fleet-enrollment-form-grid">
          <label>
            <span>Control-plane IP</span>
            <input type="text" value={dialogState.ip ?? ''} onChange={(event) => updateDialogState('ip', event.target.value)} />
          </label>
          <label>
            <span>MAVLink port</span>
            <input type="number" min="1" value={dialogState.mavlink_port ?? ''} onChange={(event) => updateDialogState('mavlink_port', event.target.value)} />
          </label>
          <label>
            <span>Serial port</span>
            <input type="text" value={dialogState.serial_port ?? ''} onChange={(event) => updateDialogState('serial_port', event.target.value)} />
          </label>
          <label>
            <span>Baudrate</span>
            <input type="number" min="0" value={dialogState.baudrate ?? ''} onChange={(event) => updateDialogState('baudrate', event.target.value)} />
          </label>
        </div>
        <label className="fleet-enrollment-form-stack">
          <span>Notes</span>
          <textarea rows="3" value={dialogState.notes ?? ''} onChange={(event) => updateDialogState('notes', event.target.value)} />
        </label>
        <label className="fleet-enrollment-checkbox">
          <input type="checkbox" checked={Boolean(dialogState.commit)} onChange={(event) => updateDialogState('commit', event.target.checked)} />
          <span>Commit and push repo changes after recovery</span>
        </label>
      </ActionDialog>

      <ActionDialog
        isOpen={dialogMode === 'ignore'}
        title="Ignore candidate"
        description="Keep the candidate in history without changing fleet config."
        busy={busy}
        onClose={closeDialog}
        onSubmit={handleMutation}
        submitLabel="Ignore candidate"
      >
        <label className="fleet-enrollment-form-stack">
          <span>Reason (optional)</span>
          <textarea rows="3" value={dialogState.reason ?? ''} onChange={(event) => updateDialogState('reason', event.target.value)} />
        </label>
      </ActionDialog>

      <ActionDialog
        isOpen={dialogMode === 'reject'}
        title="Reject candidate"
        description="Use this when the node is invalid, duplicated, or outside the managed fleet."
        busy={busy}
        onClose={closeDialog}
        onSubmit={handleMutation}
        submitLabel="Reject candidate"
        tone="danger"
      >
        <label className="fleet-enrollment-form-stack">
          <span>Reason (optional)</span>
          <textarea rows="3" value={dialogState.reason ?? ''} onChange={(event) => updateDialogState('reason', event.target.value)} />
        </label>
      </ActionDialog>
    </div>
  );
}

export default FleetEnrollmentPage;
