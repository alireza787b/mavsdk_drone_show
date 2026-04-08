import React, { useMemo } from 'react';

const formatFindingLabel = (finding) => (
  finding?.summary || String(finding?.type || 'other').replace(/_/g, ' ')
);

const MissionHandoffPanel = ({
  handoff,
  loading,
  onCopyBrief,
  onExportJson,
}) => {
  const topFindings = useMemo(
    () => (handoff?.findings || []).slice(0, 3),
    [handoff?.findings],
  );

  return (
    <div className="qs-config-section">
      <div className="qs-config-title">Handoff</div>

      {loading ? (
        <div className="qs-empty-copy">Refreshing mission handoff…</div>
      ) : null}

      {!loading && !handoff ? (
        <div className="qs-empty-copy">
          Launch or reopen a mission to generate a handoff package for findings and follow-up coordination.
        </div>
      ) : null}

      {handoff ? (
        <>
          <div className="qs-launch-review__chip-row">
            <span className="qs-inline-chip">{handoff.finding_count} findings</span>
            <span className="qs-inline-chip">{handoff.reviewed_finding_count} reviewed</span>
            <span className="qs-inline-chip">{handoff.unresolved_finding_count} unresolved</span>
            <span className="qs-inline-chip">{handoff.evidence_ref_count} refs</span>
          </div>

          <div className="qs-launch-review__brief" style={{ marginTop: 10 }}>
            <span className="qs-launch-review__brief-label">Operator Brief</span>
            <p>{handoff.brief_text}</p>
          </div>

          {topFindings.length > 0 ? (
            <div className="qs-handoff-list">
              {topFindings.map((finding) => (
                <div key={finding.id} className="qs-handoff-item">
                  <div className="qs-handoff-item__body">
                    <strong>{formatFindingLabel(finding)}</strong>
                    <span>
                      {String(finding.type || 'other').replace(/_/g, ' ')} · {String(finding.status || 'new').replace(/_/g, ' ')}
                    </span>
                  </div>
                  <div className="qs-handoff-item__meta">
                    <span className="qs-inline-chip">{String(finding.priority || 'medium')}</span>
                    <span className="qs-inline-chip">{(finding.evidence_refs || []).length} refs</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="qs-empty-copy" style={{ marginTop: 10 }}>
              No findings are logged for this mission yet.
            </div>
          )}

          <div className="qs-finding-detail__actions" style={{ marginTop: 10 }}>
            <button
              type="button"
              className="qs-btn qs-btn-secondary"
              onClick={onCopyBrief}
            >
              Copy Brief
            </button>
            <button
              type="button"
              className="qs-btn qs-btn-secondary"
              onClick={onExportJson}
            >
              Export JSON
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
};

export default MissionHandoffPanel;
