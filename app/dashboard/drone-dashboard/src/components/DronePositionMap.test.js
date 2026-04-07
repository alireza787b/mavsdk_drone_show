import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

jest.mock('geodesy/latlon-spherical', () =>
  jest.fn().mockImplementation((lat, lon) => ({
    lat,
    lon,
    destinationPoint: jest.fn((_distance, _bearing) => ({
      lat,
      lon,
    })),
  }))
);

import DronePositionMap from './DronePositionMap';

const mockMapApi = {
  invalidateSize: jest.fn(),
  fitBounds: jest.fn(),
  setView: jest.fn(),
};

jest.mock('./map/LeafletMapBase', () => ({ children }) => (
  <div data-testid="leaflet-map-base">{children}</div>
));

jest.mock('leaflet', () => ({
  divIcon: jest.fn((payload) => payload),
  latLngBounds: jest.fn((points) => ({
    points,
    pad: jest.fn(() => ({ points })),
  })),
}));

jest.mock('react-leaflet', () => ({
  Marker: ({ children, eventHandlers }) => (
    <button type="button" onClick={() => eventHandlers?.click?.()}>
      {children}
    </button>
  ),
  CircleMarker: ({ children }) => <div>{children}</div>,
  Polyline: () => <div data-testid="launch-map-polyline" />,
  Popup: ({ children }) => <div>{children}</div>,
  useMap: () => mockMapApi,
}));

describe('DronePositionMap', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('accepts zero-value origins as valid map coordinates', () => {
    render(
      <DronePositionMap
        originLat={0}
        originLon={0}
        drones={[
          {
            hw_id: '1',
            pos_id: '1',
          },
        ]}
        deviationData={{
          deviations: {
            '1': {
              expected: { lat: 0, lon: 0 },
            },
          },
        }}
        trajectoryPositionsByPosId={{}}
        forwardHeading={0}
      />
    );

    expect(screen.queryByText(/set the origin first/i)).not.toBeInTheDocument();
    expect(screen.getByText('Launch Layout Map')).toBeInTheDocument();
    expect(screen.getByText('1 expected')).toBeInTheDocument();
  });

  it('renders expected and live summaries and keeps marker clicks operator-routable', () => {
    const onDroneClick = jest.fn();

    render(
      <DronePositionMap
        originLat={35}
        originLon={139}
        drones={[
          {
            hw_id: '1',
            pos_id: '1',
            x: 0,
            y: 0,
          },
        ]}
        deviationData={{
          deviations: {
            '1': {
              status: 'warning',
              deviation: { horizontal: 2.4 },
              expected: { lat: 35.0, lon: 139.0 },
              current: {
                lat: 35.0002,
                lon: 139.0003,
                gps_quality: 'good',
                satellites: 12,
              },
            },
          },
        }}
        trajectoryPositionsByPosId={{}}
        forwardHeading={15}
        onDroneClick={onDroneClick}
      />
    );

    expect(screen.getByText('1 expected')).toBeInTheDocument();
    expect(screen.getByText('1 live')).toBeInTheDocument();
    expect(screen.getByText('1 warn')).toBeInTheDocument();
    expect(screen.getByTestId('launch-map-polyline')).toBeInTheDocument();

    fireEvent.click(screen.getAllByRole('button')[1]);
    expect(onDroneClick).toHaveBeenCalledWith('1');
  });
});
