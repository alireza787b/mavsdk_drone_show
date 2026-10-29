import React from 'react';

// Evidence is grouped by finding, never repeated once per aircraft/sample.
export default function ShowAnalysisDetails({ validation = {}, metrics = {} }) {
  const findings = validation.findings || (validation.issues || []).map(detail => ({ title: 'Review trajectory', detail }));
  const closest = metrics.safety_metrics?.min_distance_details;
  return <div className="show-analysis-details">
    {closest && <p><strong>Closest pair: P{closest.drone_1} ↔ P{closest.drone_2}</strong>
      {' · '}{closest.distance_m} m at {closest.time_s} s from show start</p>}
    {findings.length ? <ul>{findings.map((finding, index) => <li key={index}>
      <strong>{finding.title}</strong><p>{finding.detail}</p>
      {finding.threshold_m != null && <p>Analysis separation limit: {finding.threshold_m} m</p>}
    </li>)}</ul> : <p>{validation.validation_status === 'PASS' ? 'No trajectory findings.' : 'Analysis unavailable. Reprocess the show in Design / Setup.'}</p>}
    <a href="/drone-show?tab=setup">Review trajectories in Design / Setup</a>
  </div>;
}
