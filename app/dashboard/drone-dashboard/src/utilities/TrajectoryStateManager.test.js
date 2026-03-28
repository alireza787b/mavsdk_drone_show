import { ACTION_TYPES, TrajectoryStateManager } from './TrajectoryStateManager';

const baseWaypoint = {
  id: 'wp-1',
  latitude: 35.7262,
  longitude: 51.2721,
  altitude: 100,
  timeFromStart: 0,
};

describe('TrajectoryStateManager', () => {
  it('applies waypoint updates using waypointId payloads and restores them on undo', () => {
    const manager = new TrajectoryStateManager();
    manager.setInitialState({
      waypoints: [baseWaypoint],
      selectedWaypointId: baseWaypoint.id,
      lastModified: Date.now(),
    });

    manager.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      {
        waypointId: baseWaypoint.id,
        updates: { altitude: 150 },
        waypoints: [{ ...baseWaypoint, altitude: 150 }],
      },
      'Raise waypoint altitude'
    );

    expect(manager.getCurrentState().waypoints[0].altitude).toBe(150);

    const undoResult = manager.undo();
    expect(undoResult.state.waypoints[0].altitude).toBe(100);
  });

  it('clears the selected waypoint when deleting with waypointId payloads', () => {
    const manager = new TrajectoryStateManager();
    manager.setInitialState({
      waypoints: [baseWaypoint],
      selectedWaypointId: baseWaypoint.id,
      lastModified: Date.now(),
    });

    manager.executeAction(
      ACTION_TYPES.DELETE_WAYPOINT,
      {
        waypointId: baseWaypoint.id,
        waypoints: [],
      },
      'Delete waypoint'
    );

    expect(manager.getCurrentState().waypoints).toEqual([]);
    expect(manager.getCurrentState().selectedWaypointId).toBeNull();
  });
});
