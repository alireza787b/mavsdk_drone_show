import React from 'react';
import { render, screen } from '@testing-library/react';

import RouteSketch from './RouteSketch';

describe('RouteSketch', () => {
  it('renders an empty route state', () => {
    render(<RouteSketch emptyLabel="No leader route" />);

    expect(screen.getByText('No leader route')).toBeInTheDocument();
  });

  it('does not stretch equal north/east distances independently', () => {
    render(<RouteSketch series={[{ points: [{ lat: 0, lng: 0 }, { lat: 0, lng: .001 }, { lat: .001, lng: .001 }] }]} />);
    const [a,b,c] = document.querySelector('polyline').getAttribute('points').split(' ').map((p) => p.split(',').map(Number));
    expect(Math.abs(b[0]-a[0])).toBeCloseTo(Math.abs(c[1]-b[1]), 0);
  });

  it('preserves short routes across the date line and ignores incomplete points', () => {
    render(<RouteSketch series={[{ points: [{ lat: 0, lng: 179.999 }, { lat: 0, lng: -179.999 }, { lat: 0, lng: null }] }]} />);
    const points = document.querySelector('polyline').getAttribute('points').split(' ').map((p) => p.split(',').map(Number));
    expect(points).toHaveLength(2);
    expect(points[1][0]).toBeGreaterThan(points[0][0]);
    expect(points.flat().every(Number.isFinite)).toBe(true);
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
    expect(document.querySelector('polyline')).toHaveAttribute('stroke-width', '2');
    expect(document.querySelector('polyline')).toHaveAttribute('vector-effect', 'non-scaling-stroke');
    expect(document.querySelector('path')).toHaveAttribute('vector-effect', 'non-scaling-stroke');
  });

  it('does not join a line across unavailable geographic samples', () => {
    render(<RouteSketch series={[{ id: 1, points: [{ lat: 0, lng: 0 }, { lat: null, lng: null }, { lat: .001, lng: .001 }] }]} />);
    expect(document.querySelectorAll('polyline')).toHaveLength(2);
  });
});
