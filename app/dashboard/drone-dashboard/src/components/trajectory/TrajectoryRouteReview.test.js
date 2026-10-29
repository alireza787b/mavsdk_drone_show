import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import TrajectoryRouteReview from './TrajectoryRouteReview';

const mockMap = { fitBounds: jest.fn(), invalidateSize: jest.fn() };
jest.mock('../map/LeafletMapBase', () => ({ children }) => <div data-testid="geographic-map">{children}</div>);
jest.mock('react-leaflet', () => ({
  useMap: () => mockMap,
  Polyline: ({ positions, pathOptions }) => <div data-testid="map-trace" data-points={JSON.stringify(positions)} data-color={pathOptions.color} />,
  CircleMarker: () => <span data-testid="route-start" />,
}));

const route = (id, role = 'unknown') => ({
  drone_id: id, role, global_coordinates_available: true,
  points: [{ lat: id / 1000, lng: 0 }, { lat: id / 1000 + .001, lng: .001 }],
});
const formation = [{ hw_id: 1, follow: 0 }, { hw_id: 2, follow: 1 }];
const retainedPreview = { drones: Array.from({ length: 10 }, (_, index) => route(index + 1)) };

describe('TrajectoryRouteReview', () => {
  beforeEach(() => jest.clearAllMocks());

  it('prioritizes the two assigned aircraft and keeps eight retained outputs collapsed and hidden', () => {
    render(<TrajectoryRouteReview preview={retainedPreview} formationAssignments={formation}
      fleet={[{ hw_id: 1, pos_id: 70, callsign: 'Scout' }, { hw_id: 2, name: 'Wing' }]} />);
    expect(screen.getByTestId('geographic-map')).toBeInTheDocument();
    expect(screen.getAllByTestId('map-trace')).toHaveLength(2);
    expect(screen.getByRole('checkbox', { name: 'Show Scout (H1) route' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'Show Wing (H2) route' })).toBeChecked();
    const outside = screen.getByText('Outside mission (8)').closest('details');
    expect(outside).not.toHaveAttribute('open');
    expect(within(outside).getByText(/No assignment in this mission; regenerate paths or inspect this saved output/)).toBeInTheDocument();
    expect(within(outside).getAllByRole('checkbox', { hidden: true }).every((checkbox) => !checkbox.checked)).toBe(true);
    expect(screen.queryByText(/H70/)).not.toBeInTheDocument();
    const color = screen.getAllByTestId('map-trace')[1].getAttribute('data-color');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show Scout (H1) route' }));
    expect(screen.getAllByTestId('map-trace')).toHaveLength(1);
    expect(screen.getByTestId('map-trace')).toHaveAttribute('data-color', color);
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
    expect(screen.getAllByTestId('map-trace')).toHaveLength(10);
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(2);
  });

  it('uses thin non-scaling overview traces with the same legend colors and working toggles', () => {
    render(<TrajectoryRouteReview preview={retainedPreview} formationAssignments={formation} />);
    const firstColor = screen.getAllByTestId('map-trace')[0].getAttribute('data-color');
    fireEvent.click(screen.getByRole('button', { name: 'Overview' }));
    const svg = screen.getByRole('img', { name: 'Route preview' });
    expect(svg.querySelectorAll('polyline')).toHaveLength(2);
    expect(svg.querySelector('polyline')).toHaveAttribute('stroke', firstColor);
    expect(svg.querySelector('polyline')).toHaveAttribute('stroke-width', '2');
    expect(svg.querySelector('polyline')).toHaveAttribute('vector-effect', 'non-scaling-stroke');
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show H2 route' }));
    expect(svg.querySelectorAll('polyline')).toHaveLength(1);
    expect(document.querySelector('[data-aircraft-id="1"] i').style.backgroundColor).toBe(firstColor);
  });

  it('does not present unknown retained output as a mission aircraft when no known assignment exists', () => {
    render(<TrajectoryRouteReview preview={{ drones: [route(8)] }} />);
    expect(screen.getByText('No routes assigned to this mission')).toBeInTheDocument();
    expect(screen.queryByTestId('geographic-map')).not.toBeInTheDocument();
    const outside = screen.getByText('Outside mission (1)').closest('details');
    fireEvent.click(within(outside).getByRole('checkbox', { name: 'Show H8 route', hidden: true }));
    expect(screen.getByTestId('map-trace')).toBeInTheDocument();
    expect(within(outside).getByText('Role unknown')).toBeInTheDocument();
  });

  it('excludes invalid geometry from both legend and map and retains real origin geometry', () => {
    render(<TrajectoryRouteReview preview={{ drones: [
      { ...route(1, 'leader'), points: [{ lat: 0, lng: 0 }, { lat: 0, lng: .001 }] },
      { ...route(2, 'follower'), points: [{ lat: null, lng: null }] },
    ] }} />);
    expect(screen.getAllByTestId('map-trace')).toHaveLength(1);
    expect(screen.getByRole('checkbox', { name: 'Show H1 route' })).toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: 'Show H2 route' })).not.toBeInTheDocument();
    const fitted = mockMap.fitBounds.mock.calls[0][0];
    expect(fitted[0]).toEqual([0, 0]);
    expect(fitted[1][0]).toBe(0);
    expect(fitted[1][1]).toBeCloseTo(.001);
  });

  it('fits at package changes and explicit Fit only, not search or checkbox changes', () => {
    const preview = { drones: [route(1), route(2)] };
    const { rerender } = render(<TrajectoryRouteReview preview={preview} formationAssignments={formation} packageIdentity="first" />);
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('checkbox', { name: 'Show H2 route' }));
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Fit visible routes' }));
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(2);
    rerender(<TrajectoryRouteReview preview={preview} formationAssignments={formation} packageIdentity="second" />);
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(3);
    expect(screen.getByRole('checkbox', { name: 'Show H2 route' })).toBeChecked();
  });

  it('supports searching 50 aircraft without silently filtering the map, and Show all resets search', () => {
    const preview = { drones: Array.from({ length: 50 }, (_, index) => route(index + 1, index ? 'follower' : 'leader')) };
    render(<TrajectoryRouteReview preview={preview} />);
    expect(screen.getAllByTestId('map-trace')).toHaveLength(50);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find aircraft routes' }), { target: { value: 'H50' } });
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    expect(screen.getByRole('checkbox', { name: 'Show H50 route' })).toBeInTheDocument();
    expect(screen.getAllByTestId('map-trace')).toHaveLength(50);
    expect(mockMap.fitBounds).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
    expect(screen.getByRole('searchbox')).toHaveValue('');
    expect(screen.getAllByRole('checkbox')).toHaveLength(50);
  });
});
