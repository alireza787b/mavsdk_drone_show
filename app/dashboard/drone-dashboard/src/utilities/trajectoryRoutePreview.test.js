import {
  normalizeTrajectoryPreviewRoutes, routeGeographicBounds, routePointSegments, trajectoryRouteColor,
} from './trajectoryRoutePreview';

describe('trajectoryRoutePreview', () => {
  it('uses actual hardware labels and explicit mission links without inferring leaders from missing links', () => {
    const routes = normalizeTrajectoryPreviewRoutes({ drones: [
      { drone_id: 1, role: 'unknown', points: [{ lat: 0, lng: 0 }] },
      { drone_id: 2, role: 'unknown', points: [{ lat: 0, lng: .001 }] },
      { drone_id: 3, role: 'unknown', direct_leader_id: null, points: [{ lat: 0, lng: .002 }] },
    ] }, [{ hw_id: 1, follow: 0 }, { hw_id: 2, follow: 1 }], [{ hw_id: 1, pos_id: 99, callsign: 'Scout' }]);
    expect(routes[0]).toEqual(expect.objectContaining({ id: '1', label: 'Scout', hardwareLabel: 'H1', role: 'leader', outsideMission: false }));
    expect(routes[1]).toEqual(expect.objectContaining({ id: '2', label: 'H2', role: 'follower', leaderId: '1', outsideMission: false }));
    expect(routes[2]).toEqual(expect.objectContaining({ id: '3', role: 'unknown', roleLabel: 'Role unknown', leaderId: null, outsideMission: true }));
  });

  it('keeps a missing relationship unknown even when its aircraft is explicitly a mission member', () => {
    const [route] = normalizeTrajectoryPreviewRoutes({ drones: [{ drone_id: 1, role: 'unknown', points: [{ lat: 0, lng: 0 }] }] }, [{ hw_id: 1 }]);
    expect(route.role).toBe('unknown');
    expect(route.outsideMission).toBe(false);
  });

  it('derives both display lists and traces only from renderable paths, preserving zeros and gaps', () => {
    const routes = normalizeTrajectoryPreviewRoutes({ drones: [
      { drone_id: 1, role: 'leader', points: [{ lat: 0, lng: 0 }, { lat: null, lng: null }, { lat: .001, lng: 0 }] },
      { drone_id: 2, role: 'follower', points: [{ lat: 91, lng: 0 }, { lat: 0, lng: NaN }] },
      { drone_id: 0, role: 'leader', points: [{ lat: 0, lng: 0 }] },
    ] });
    expect(routes.map((route) => route.id)).toEqual(['1']);
    expect(routes[0].points[0]).toEqual(expect.objectContaining({ latitude: 0, longitude: 0 }));
    expect(routes[0].segments).toHaveLength(2);
    expect(routePointSegments([{ lat: 0, lng: 0 }, { lat: null, lng: 0 }, { lat: 0, lng: 1 }])).toHaveLength(2);
  });

  it('anchors colors to hardware independently of filtering or ordering and uses global theme tokens', () => {
    const all = { drones: [1, 2].map((drone_id) => ({ drone_id, role: 'leader', points: [{ lat: 0, lng: 0 }] })) };
    const color = normalizeTrajectoryPreviewRoutes(all)[1].color;
    expect(normalizeTrajectoryPreviewRoutes({ drones: [all.drones[1]] })[0].color).toBe(color);
    expect(trajectoryRouteColor('02')).toBe(color);
    expect(color).not.toContain('--route-sketch-color');
  });

  it('keeps date-line bounds short and the coordinate frame stable when paths are hidden', () => {
    const series = [{ points: [{ lat: 0, lng: 179.999 }, { lat: 0, lng: -179.999 }] }];
    const bounds = routeGeographicBounds(series);
    expect(bounds.maxLng - bounds.minLng).toBeCloseTo(.002, 5);
    const filtered = routeGeographicBounds([{ points: [{ lat: 0, lng: 179.999 }] }], bounds);
    expect(filtered.unwrap(179.999)).toBe(bounds.unwrap(179.999));
    expect(routeGeographicBounds([{ points: [{ lat: null, lng: 0 }] }])).toBeNull();
  });
});
