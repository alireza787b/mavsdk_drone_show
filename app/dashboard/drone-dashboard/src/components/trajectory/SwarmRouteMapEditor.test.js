import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import SwarmRouteMapEditor from './SwarmRouteMapEditor';

let mockMapContext = {
  provider: 'leaflet',
  isMapboxAvailable: false,
  mapboxToken: '',
};

jest.mock('../../contexts/MapContext', () => ({
  useMapContext: () => mockMapContext,
}));

jest.mock('../map/LeafletMapBase', () => ({ children, onClick }) => (
  <div data-testid="leaflet-route-map">
    <button type="button" onClick={() => onClick?.({ latlng: { lat: 35.1, lng: 51.2 } })}>
      Leaflet map click
    </button>
    {children}
  </div>
));

jest.mock('../map/MapFallbackBanner', () => () => <div data-testid="map-fallback-banner" />);
jest.mock('../map/MapProviderToggle', () => () => <div data-testid="map-provider-toggle" />);
jest.mock('react-leaflet', () => ({
  CircleMarker: () => <div data-testid="leaflet-circle-marker" />,
  Polyline: () => <div data-testid="leaflet-polyline" />,
}));

jest.mock('react-map-gl', () => {
  const Map = ({ children, onClick }) => (
    <div data-testid="mapbox-route-map">
      <button type="button" onClick={() => onClick?.({ lngLat: { lat: 35.3, lng: 51.4 } })}>
        Mapbox map click
      </button>
      {children}
    </div>
  );
  return {
    __esModule: true,
    default: Map,
    Map,
    Marker: ({ children }) => <div data-testid="mapbox-marker">{children}</div>,
    Source: ({ children }) => <div data-testid="mapbox-source">{children}</div>,
    Layer: () => <div data-testid="mapbox-layer" />,
  };
});

describe('SwarmRouteMapEditor', () => {
  beforeEach(() => {
    mockMapContext = {
      provider: 'leaflet',
      isMapboxAvailable: false,
      mapboxToken: '',
    };
  });

  it('uses Leaflet fallback and emits clicked waypoint coordinates', () => {
    const onAddWaypoint = jest.fn();
    render(
      <SwarmRouteMapEditor
        waypoints={[{ id: 'wp-1', latitude: 35, longitude: 51 }]}
        onAddWaypoint={onAddWaypoint}
        altitudeLabel="Fixed MSL"
      />
    );

    expect(screen.getByTestId('map-fallback-banner')).toBeInTheDocument();
    expect(screen.getByText('1 waypoint · Fixed MSL')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Leaflet map click' }));
    expect(onAddWaypoint).toHaveBeenCalledWith({ latitude: 35.1, longitude: 51.2, source: 'map' });
  });

  it('uses Mapbox when available and keeps route markers visible', () => {
    mockMapContext = {
      provider: 'mapbox',
      isMapboxAvailable: true,
      mapboxToken: 'token',
    };
    const onAddWaypoint = jest.fn();
    render(
      <SwarmRouteMapEditor
        waypoints={[
          { id: 'wp-1', latitude: 35, longitude: 51 },
          { id: 'wp-2', latitude: 35.01, longitude: 51.02 },
        ]}
        onAddWaypoint={onAddWaypoint}
        altitudeLabel="AGL terrain"
      />
    );

    expect(screen.getByTestId('mapbox-route-map')).toBeInTheDocument();
    expect(screen.getAllByTestId('mapbox-marker')).toHaveLength(2);
    expect(screen.getByText('2 waypoints · AGL terrain')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Mapbox map click' }));
    expect(onAddWaypoint).toHaveBeenCalledWith({ latitude: 35.3, longitude: 51.4, source: 'map' });
  });
});
