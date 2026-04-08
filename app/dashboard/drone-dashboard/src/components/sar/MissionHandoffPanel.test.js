import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import MissionHandoffPanel from './MissionHandoffPanel';

describe('MissionHandoffPanel', () => {
  it('renders handoff summary and delegates export actions', () => {
    const onCopyBrief = jest.fn();
    const onExportJson = jest.fn();

    render(
      <MissionHandoffPanel
        loading={false}
        handoff={{
          mission_id: 'mission-1',
          finding_count: 2,
          reviewed_finding_count: 1,
          unresolved_finding_count: 1,
          evidence_ref_count: 3,
          brief_text: 'Harbor sweep is executing in searching phase.',
          findings: [
            {
              id: 'finding-1',
              summary: 'Possible survivor',
              type: 'person',
              status: 'confirmed',
              priority: 'critical',
              evidence_refs: ['img://capture-1'],
            },
          ],
        }}
        onCopyBrief={onCopyBrief}
        onExportJson={onExportJson}
      />
    );

    expect(screen.getByText('Handoff')).toBeInTheDocument();
    expect(screen.getByText('2 findings')).toBeInTheDocument();
    expect(screen.getByText('Harbor sweep is executing in searching phase.')).toBeInTheDocument();
    expect(screen.getByText('Possible survivor')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Copy Brief' }));
    fireEvent.click(screen.getByRole('button', { name: 'Export JSON' }));

    expect(onCopyBrief).toHaveBeenCalledTimes(1);
    expect(onExportJson).toHaveBeenCalledTimes(1);
  });
});
