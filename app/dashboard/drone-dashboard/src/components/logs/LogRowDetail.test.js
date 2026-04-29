import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import LogRowDetail from './LogRowDetail';

describe('LogRowDetail', () => {
  it('renders a centered dialog with readable log details', () => {
    render(
      <LogRowDetail
        entry={{
          _id: 1,
          ts: '2026-04-29T16:50:04.434Z',
          level: 'WARNING',
          component: 'drone_api',
          source: 'drone',
          drone_id: 2,
          msg: 'GCS responded with status code 404',
          extra: { route: '/api/v1/origin' },
        }}
        onClose={jest.fn()}
      />
    );

    expect(screen.getByRole('dialog', { name: /warning/i })).toBeInTheDocument();
    expect(screen.getByText('GCS responded with status code 404')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getAllByText(/api\/v1\/origin/i).length).toBeGreaterThan(0);
  });

  it('closes from the dialog close button', () => {
    const onClose = jest.fn();
    render(
      <LogRowDetail
        entry={{
          _id: 1,
          level: 'INFO',
          component: 'gcs',
          msg: 'Started',
        }}
        onClose={onClose}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /close log detail/i }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
