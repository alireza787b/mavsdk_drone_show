import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import TrajectoryExportDialog from './TrajectoryExportDialog';

describe('TrajectoryExportDialog', () => {
  it('defaults to CSV export and lets the operator switch formats explicitly', () => {
    const onExport = jest.fn();

    render(
      <TrajectoryExportDialog
        isOpen
        onClose={jest.fn()}
        onExport={onExport}
        trajectoryName="route-alpha"
      />
    );

    expect(screen.getByText(/choose the output format for/i)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: /csv/i })).toBeChecked();

    fireEvent.click(screen.getByRole('radio', { name: /kml/i }));
    fireEvent.click(screen.getByRole('button', { name: /export kml/i }));

    expect(onExport).toHaveBeenCalledWith('kml');
  });
});
