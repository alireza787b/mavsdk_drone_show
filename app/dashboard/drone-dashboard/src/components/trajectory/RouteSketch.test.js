import React from 'react';
import { render, screen } from '@testing-library/react';

import RouteSketch from './RouteSketch';

describe('RouteSketch', () => {
  it('renders an empty route state', () => {
    render(<RouteSketch emptyLabel="No leader route" />);

    expect(screen.getByText('No leader route')).toBeInTheDocument();
  });

  it('renders leader and follower route polylines from lat/lng variants', () => {
    render(
      <RouteSketch
        series={[
          {
            id: 'leader',
            role: 'leader',
            points: [
              { latitude: 35, longitude: 51 },
              { latitude: 35.01, longitude: 51.02 },
            ],
          },
          {
            id: 'follower',
            role: 'follower',
            points: [
              { lat: 35, lng: 51.001 },
              { lat: 35.01, lng: 51.021 },
            ],
          },
        ]}
      />
    );

    expect(screen.getByRole('img', { name: 'Route preview' })).toBeInTheDocument();
    expect(document.querySelectorAll('polyline')).toHaveLength(2);
    expect(document.querySelector('polyline')).toHaveAttribute('stroke-width', '4');
  });
});
