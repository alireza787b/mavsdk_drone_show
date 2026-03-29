import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import TrajectoryExportDialog from './TrajectoryExportDialog';

describe('TrajectoryExportDialog', () => {
  it('explains that CSV export is a leader authoring route, not the processed mission package', () => {
    const onExport = jest.fn();

    render(
      <TrajectoryExportDialog
        isOpen
        onClose={jest.fn()}
        onExport={onExport}
        trajectoryName="Harbor Sweep"
      />
    );

    expect(screen.getByText('Export Leader Route')).toBeInTheDocument();
    expect(screen.getByText(/leader authoring CSV/i)).toBeInTheDocument();
    expect(screen.getByText(/not the processed multi-drone mission package/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /export csv/i }));

    expect(onExport).toHaveBeenCalledWith('csv');
  });
});
