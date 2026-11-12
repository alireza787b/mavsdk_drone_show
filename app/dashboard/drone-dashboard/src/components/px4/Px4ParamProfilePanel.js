import React from 'react';
import { ChangeTable } from './ParameterReview';

export default function Px4ParamProfilePanel({ profile, loading, compareTargetLabel, compareResult, compareLoading, onPreviewDiff, onReview, onExportProfile }) {
  if (loading) return <p className="px4-empty" role="status">Loading profile…</p>;
  if (!profile) return <p className="px4-empty">Choose a profile to inspect its values.</p>;
  return <section className="px4-profile" aria-label="Selected profile">
    <header className="px4-profile-heading"><div><h2>{profile.name}</h2><span>{profile.entries.length} parameters · {profile.recommended_scope} guidance</span></div>
      <div className="px4-text-actions"><button type="button" className="operator-button operator-button--primary" onClick={onReview}>Review for aircraft</button>
        <button type="button" className="operator-button operator-button--ghost" disabled={!compareTargetLabel || compareLoading} onClick={onPreviewDiff}>{compareLoading ? 'Comparing…' : 'Compare snapshot'}</button>
        <button type="button" className="operator-button operator-button--ghost" onClick={onExportProfile}>Export JSON</button></div></header>
    {profile.description && <p>{profile.description}</p>}
    {!!profile.tags?.length && <p className="px4-muted">{profile.tags.join(' · ')}</p>}
    {compareResult && <details className="px4-details" open><summary>{compareResult.total_changed} differences · {compareTargetLabel}</summary><ChangeTable entries={compareResult.differences || []} desired /></details>}
    <ChangeTable entries={profile.entries} />
    <details className="px4-details"><summary>Profile source</summary><p>Repo-managed · <code>resources/px4_param_profiles/</code></p><p>Review and apply here. Add or revise profiles through the repository workflow.</p></details>
  </section>;
}
