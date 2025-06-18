// src/pages/TrajectoryPlanning.js
import React, { useState, useRef, useEffect } from 'react';
import { Viewer, Entity, PolylineGraphics, PointGraphics, Cesium3DTileset, CameraFlyTo } from 'resium';
import { 
  Cartesian3, 
  Color, 
  ScreenSpaceEventType, 
  createWorldTerrain, 
  IonResource,
  ScreenSpaceEventHandler,
  defined,
  Cartesian2,
  VerticalOrigin,
  HorizontalOrigin,
  Math as CesiumMath,
  sampleTerrainMostDetailed,
  Cartographic
} from 'cesium';
import "cesium/Build/Cesium/Widgets/widgets.css";
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import '../styles/TrajectoryPlanning.css';

const TrajectoryPlanning = () => {
  const viewerRef = useRef(null);
  const [waypoints, setWaypoints] = useState([]);
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [isAddingWaypoint, setIsAddingWaypoint] = useState(false);
  const [showTerrain, setShowTerrain] = useState(true);
  const [sceneMode, setSceneMode] = useState('3D');
  const [trajectoryStats, setTrajectoryStats] = useState({
    totalDistance: 0,
    totalTime: 0,
    maxAltitude: 0,
    minAltitude: 0,
  });

  // Cesium Ion access token (you should move this to environment variable)
  const cesiumIonToken = process.env.REACT_APP_CESIUM_ION_TOKEN || 'your-cesium-ion-token';

  // Set up terrain provider
  const terrainProvider = showTerrain ? createWorldTerrain() : null;

  // Calculate trajectory statistics
  useEffect(() => {
    if (waypoints.length < 2) {
      setTrajectoryStats({
        totalDistance: 0,
        totalTime: 0,
        maxAltitude: waypoints[0]?.altitude || 0,
        minAltitude: waypoints[0]?.altitude || 0,
      });
      return;
    }

    let totalDistance = 0;
    let totalTime = 0;
    let maxAlt = waypoints[0].altitude;
    let minAlt = waypoints[0].altitude;

    for (let i = 1; i < waypoints.length; i++) {
      const prev = waypoints[i - 1];
      const curr = waypoints[i];

      // Calculate distance using Cartesian3
      const prevPos = Cartesian3.fromDegrees(prev.longitude, prev.latitude, prev.altitude);
      const currPos = Cartesian3.fromDegrees(curr.longitude, curr.latitude, curr.altitude);
      const distance = Cartesian3.distance(prevPos, currPos);
      
      totalDistance += distance;
      totalTime = Math.max(totalTime, curr.time);
      maxAlt = Math.max(maxAlt, curr.altitude);
      minAlt = Math.min(minAlt, curr.altitude);
    }

    setTrajectoryStats({
      totalDistance,
      totalTime,
      maxAltitude: maxAlt,
      minAltitude: minAlt,
    });
  }, [waypoints]);

  // Set up click handler for adding waypoints
  useEffect(() => {
    if (!viewerRef.current || !isAddingWaypoint) return;

    const viewer = viewerRef.current.cesiumElement;
    if (!viewer || !viewer.scene) return;

    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((click) => {
      const cartesian = viewer.camera.pickEllipsoid(
        click.position,
        viewer.scene.globe.ellipsoid
      );

      if (defined(cartesian)) {
        const cartographic = Cartographic.fromCartesian(cartesian);
        const longitude = CesiumMath.toDegrees(cartographic.longitude);
        const latitude = CesiumMath.toDegrees(cartographic.latitude);

        // Sample terrain height at this position
        if (viewer.terrainProvider) {
          sampleTerrainMostDetailed(viewer.terrainProvider, [cartographic])
            .then((updatedPositions) => {
              const terrainHeight = updatedPositions[0].height || 0;
              addWaypoint(longitude, latitude, terrainHeight);
            })
            .catch(() => {
              // If terrain sampling fails, use 0
              addWaypoint(longitude, latitude, 0);
            });
        } else {
          addWaypoint(longitude, latitude, 0);
        }
      }
    }, ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      handler.destroy();
    };
  }, [isAddingWaypoint, viewerRef.current]);

  const addWaypoint = (longitude, latitude, terrainHeight) => {
    const newWaypoint = {
      id: Date.now(),
      name: `Waypoint ${waypoints.length + 1}`,
      latitude,
      longitude,
      altitude: terrainHeight + 100, // Default 100m AGL
      terrainHeight,
      time: waypoints.length * 10, // Default 10 seconds between waypoints
      speed: 10, // Default 10 m/s
    };

    setWaypoints([...waypoints, newWaypoint]);
    setIsAddingWaypoint(false);
  };

  const updateWaypoint = (id, updates) => {
    setWaypoints(waypoints.map(wp => 
      wp.id === id ? { ...wp, ...updates } : wp
    ));
  };

  const deleteWaypoint = (id) => {
    setWaypoints(waypoints.filter(wp => wp.id !== id));
    if (selectedWaypointId === id) {
      setSelectedWaypointId(null);
    }
  };

  const moveWaypoint = (fromIndex, toIndex) => {
    const newWaypoints = [...waypoints];
    const [movedWaypoint] = newWaypoints.splice(fromIndex, 1);
    newWaypoints.splice(toIndex, 0, movedWaypoint);
    setWaypoints(newWaypoints);
  };

  const clearTrajectory = () => {
    if (window.confirm('Are you sure you want to clear all waypoints?')) {
      setWaypoints([]);
      setSelectedWaypointId(null);
    }
  };

  const exportTrajectory = () => {
    if (waypoints.length === 0) {
      alert('No waypoints to export');
      return;
    }

    const csv = [
      'Name,Latitude,Longitude,Altitude (m),Time (s),Speed (m/s)',
      ...waypoints.map(wp => 
        `${wp.name},${wp.latitude},${wp.longitude},${wp.altitude},${wp.time},${wp.speed || 10}`
      )
    ].join('\n');

    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trajectory_${new Date().toISOString()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleLocationSelect = (longitude, latitude, altitude) => {
    if (viewerRef.current) {
      const viewer = viewerRef.current.cesiumElement;
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(longitude, latitude, altitude),
        duration: 2,
      });
    }
  };

  const flyToWaypoint = (waypoint) => {
    if (viewerRef.current) {
      const viewer = viewerRef.current.cesiumElement;
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(
          waypoint.longitude,
          waypoint.latitude,
          waypoint.altitude + 500
        ),
        duration: 1.5,
      });
    }
  };

  // Create trajectory line positions
  const trajectoryPositions = waypoints.map(wp =>
    Cartesian3.fromDegrees(wp.longitude, wp.latitude, wp.altitude)
  );

  return (
    <div className="trajectory-planning">
      <div className="trajectory-header">
        <div className="header-left">
          <h1>Trajectory Planning</h1>
          <SearchBar onLocationSelect={handleLocationSelect} />
        </div>
        <TrajectoryStats stats={trajectoryStats} />
      </div>

      <div className="trajectory-container">
        <div className="trajectory-main">
          <TrajectoryToolbar
            isAddingWaypoint={isAddingWaypoint}
            onToggleAddWaypoint={() => setIsAddingWaypoint(!isAddingWaypoint)}
            onClearTrajectory={clearTrajectory}
            onExportTrajectory={exportTrajectory}
            showTerrain={showTerrain}
            onToggleTerrain={() => setShowTerrain(!showTerrain)}
            sceneMode={sceneMode}
            onSceneModeChange={setSceneMode}
            waypointCount={waypoints.length}
          />

          <div className="cesium-container">
            <Viewer
              ref={viewerRef}
              full
              terrainProvider={terrainProvider}
              sceneMode={
                sceneMode === '2D' ? 0 : 
                sceneMode === '3D' ? 3 : 
                1 // Columbus view
              }
              creditContainer={document.createElement("div")}
              homeButton={false}
              sceneModePicker={false}
              baseLayerPicker={false}
              navigationHelpButton={false}
              animation={false}
              timeline={false}
              fullscreenButton={false}
              vrButton={false}
            >
              {/* Trajectory line */}
              {trajectoryPositions.length > 1 && (
                <Entity>
                  <PolylineGraphics
                    positions={trajectoryPositions}
                    width={3}
                    material={Color.fromCssColorString('#00d4ff')}
                    clampToGround={false}
                  />
                </Entity>
              )}

              {/* Waypoint markers */}
              {waypoints.map((waypoint, index) => (
                <Entity
                  key={waypoint.id}
                  position={Cartesian3.fromDegrees(
                    waypoint.longitude,
                    waypoint.latitude,
                    waypoint.altitude
                  )}
                  onClick={() => setSelectedWaypointId(waypoint.id)}
                >
                  <PointGraphics
                    pixelSize={selectedWaypointId === waypoint.id ? 15 : 10}
                    color={
                      index === 0 ? Color.GREEN :
                      index === waypoints.length - 1 ? Color.RED :
                      selectedWaypointId === waypoint.id ? Color.YELLOW :
                      Color.WHITE
                    }
                    outlineColor={Color.BLACK}
                    outlineWidth={2}
                  />
                </Entity>
              ))}

              {/* 3D Buildings (optional) */}
              {showTerrain && (
                <Cesium3DTileset
                  url={IonResource.fromAssetId(96188)}
                  onReady={(tileset) => {
                    if (viewerRef.current) {
                      viewerRef.current.cesiumElement.zoomTo(tileset);
                    }
                  }}
                />
              )}
            </Viewer>
          </div>
        </div>

        <WaypointPanel
          waypoints={waypoints}
          selectedWaypointId={selectedWaypointId}
          onSelectWaypoint={setSelectedWaypointId}
          onUpdateWaypoint={updateWaypoint}
          onDeleteWaypoint={deleteWaypoint}
          onMoveWaypoint={moveWaypoint}
          onFlyTo={flyToWaypoint}
        />
      </div>
    </div>
  );
};

export default TrajectoryPlanning;