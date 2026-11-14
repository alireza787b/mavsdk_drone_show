import React, { useId } from 'react';
import { FaPaperPlane, FaChevronDown, FaEyeSlash, FaExclamationTriangle } from 'react-icons/fa';
import './CommandAircraft.css';

export default function CommandAircraftControl({ ids, aircraft, review, totalCount, map = false, disabled = false, onOpen, onShowRecipients }) {
  const descriptionId = useId();
  const names = ids.map(id => aircraft.find(item => item.id === id)?.label || `H${id}`);
  const summary = names.length <= 3 ? names.join(', ') : `${names.slice(0, 2).join(', ')} +${names.length - 2}`;
  return <div className="command-aircraft-control">
    <button type="button" className="command-aircraft-control__choose" aria-label="Choose command aircraft"
      aria-describedby={descriptionId} data-recipient-count={ids.length} disabled={disabled} onClick={onOpen}
      title={`Command recipients: ${names.join(', ') || 'None'}`}>
      <FaPaperPlane aria-hidden="true" /><span className="command-aircraft-control__label">To</span>
      <span className="command-aircraft-control__names">{summary || '—'}</span>
      <strong title={Number.isInteger(totalCount) ? `${ids.length} of ${totalCount} aircraft are command targets` : undefined}>
        {ids.length}{Number.isInteger(totalCount) ? `/${totalCount}` : ''}</strong><FaChevronDown aria-hidden="true" />
    </button>
    <span id={descriptionId} className="command-aircraft-control__description">{ids.length} command aircraft: {names.join(', ') || 'None'}</span>
    {review.unresolvedIds.length > 0 && <button type="button" className="command-aircraft-control__missing" onClick={onOpen}
      disabled={disabled} title={`Missing from configuration: ${review.unresolvedIds.join(', ')}`} aria-label="Review missing command aircraft">
      <FaExclamationTriangle aria-hidden="true" />{review.unresolvedIds.length} missing</button>}
    {review.hiddenIds.length > 0 && <button type="button" className="command-aircraft-control__hidden" onClick={onShowRecipients}
      aria-label={`Show ${review.hiddenIds.length} command aircraft outside this ${map ? 'map' : 'view'}`}
      title={`${review.hiddenIds.length} command recipients ${map ? 'not on this map' : 'not shown'}`}>
      <FaEyeSlash aria-hidden="true" /><span>{review.hiddenIds.length}</span>
    </button>}
  </div>;
}
