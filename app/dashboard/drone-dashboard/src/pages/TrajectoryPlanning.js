// src/pages/TrajectoryPlanning.js
import React, { useState, useEffect, useRef } from 'react';
import {
  Viewer,
  Entity,
  PointGraphics,
  PolylineGraphics,
  LabelGraphics,
  CameraFlyTo,
  PolygonGraphics,
  Cartesian2
} from 'resium';
import {
  Cartesian3,
  Color,
  Ion,
  createWorldTerrain,
  VerticalOrigin,
  HorizontalOrigin,
  Cartographic,
  Math as CesiumMath,
  ScreenSpaceEventType,
  defined,
  ScreenSpaceEventHandler,
  JulianDate,
  SampledPositionProperty,
  PathGraphics,
  ConstantProperty
} from 'cesium';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import WaypointPanel from '../components/trajectory/WaypointPanel';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import '../styles/TrajectoryPlanning.css';

// Set Cesium Ion token
Ion.defaultAccessToken = process.env.REACT_APP_CESIUM_ION_TOKEN;

const TrajectoryPlanning = () => {
  const viewerRef = useRef(null);
  const [waypoints, setWaypoints] = useState([]);
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [isAddingWaypoint, setIsAddingWaypoint] = useState(false);
  const [showPath, setShowPath] = useState(true);
  const [showTerrain, setShowTerrain] = useState(true);
  const [pathInterpolation, setPathInterpolation] = useState('linear');
  const [viewMode, setViewMode] = useState('3D'); // 2D, 3D, CV (Columbus View)
  const [trajectoryStats, setTrajectoryStats] = useState({
    totalDistance: 0,
    totalTime: 0,
    maxAltitude: 0,
    minAltitude: 0
  });

  // Calculate trajectory statistics
  useEffect(() => {
    if (waypoints.length < 2) {
      setTrajectoryStats({
        totalDistance: 0,
        totalTime: 0,
        maxAltitude: 0,
        minAltitude: 0
      });
      return;
    }

    let totalDistance = 0;
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
      maxAlt = Math.max(maxAlt, curr.altitude);
      minAlt = Math.min(minAlt, curr.altitude);
    }

    const totalTime = waypoints[waypoints.length - 1].time || 0;

    setTrajectoryStats({
      totalDistance: totalDistance,
      totalTime: totalTime,
      maxAltitude: maxAlt,
      minAltitude: minAlt
    });
  }, [waypoints]);

  // Mouse click handler for adding waypoints
  useEffect(() => {
    if (!viewerRef.current || !viewerRef.current.cesiumElement) return;

    const viewer = viewerRef.current.cesiumElement;
    const handler = new ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((click) => {
      if (!isAddingWaypoint) return;

      const cartesian = viewer.camera.pickEllipsoid(
        click.position,
        viewer.scene.globe.ellipsoid
      );

      if (defined(cartesian)) {
        const cartographic = Cartographic.fromCartesian(cartesian);
        const longitude = CesiumMath.toDegrees(cartographic.longitude);
        const latitude = CesiumMath.toDegrees(cartographic.latitude);
        
        // Get terrain height at this position
        const terrainProvider = viewer.terrainProvider;
        const positions = [Cartographic.fromDegrees(longitude, latitude)];
        
        Cesium.sampleTerrainMostDetailed(terrainProvider, positions).then((updatedPositions) => {
          const terrainHeight = updatedPositions[0].height || 0;
          
          addWaypoint({
            longitude,
            latitude,
            altitude: terrainHeight + 100, // Default 100m AGL
            terrainHeight: terrainHeight,
          });
        });
      }
    }, ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      handler.destroy();
    };
  }, [isAddingWaypoint]);

  const addWaypoint = (waypointData) => {
    const newWaypoint = {
      id: Date.now(),
      name: `WP${waypoints.length + 1}`,
      latitude: waypointData.latitude,
      longitude: waypointData.longitude,
      altitude: waypointData.altitude,
      terrainHeight: waypointData.terrainHeight || 0,
      time: waypoints.length * 10, // Default 10 seconds between waypoints
      speed: 10, // m/s
      ...waypointData,
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
    
    // Recalculate times based on order
    let cumulativeTime = 0;
    newWaypoints.forEach((wp, index) => {
      if (index === 0) {
        wp.time = 0;
      } else {
        const prevWp = newWaypoints[index - 1];
        const distance = Cartesian3.distance(
          Cartesian3.fromDegrees(prevWp.longitude, prevWp.latitude, prevWp.altitude),
          Cartesian3.fromDegrees(wp.longitude, wp.latitude, wp.altitude)
        );
        const timeToNext = distance / (wp.speed || 10);
        cumulativeTime += timeToNext;
        wp.time = cumulativeTime;
      }
    });
    
    setWaypoints(newWaypoints);
  };

  const flyToLocation = (lon, lat, alt = 5000) => {
    if (viewerRef.current && viewerRef.current.cesiumElement) {
      const viewer = viewerRef.current.cesiumElement;
      viewer.camera.flyTo({
        destination: Cartesian3.fromDegrees(lon, lat, alt),
        duration: 2,
        orientation: {
          heading: 0,
          pitch: CesiumMath.toRadians(-45),
          roll: 0
        }
      });
    }
  };

  const exportTrajectory = () => {
    if (waypoints.length === 0) {
      alert('No waypoints to export');
      return;
    }

    // Create CSV content
    const headers = ['Name', 'Latitude', 'Longitude', 'Altitude (m)', 'Time (s)', 'Speed (m/s)', 'Terrain Height (m)', 'AGL (m)'];
    const rows = waypoints.map(wp => [
      wp.name,
      wp.latitude.toFixed(6),
      wp.longitude.toFixed(6),
      wp.altitude.toFixed(1),
      wp.time.toFixed(1),
      wp.speed.toFixed(1),
      wp.terrainHeight.toFixed(1),
      (wp.altitude - wp.terrainHeight).toFixed(1)
    ]);

    const csvContent = [
      headers.join(','),
      ...rows.map(row => row.join(','))
    ].join('\n');

    // Download file
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trajectory_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="trajectory-planning">
      <div className="trajectory-header">
        <div className="header-left">
          <h1>Trajectory Planning</h1>
          <TrajectoryStats stats={trajectoryStats} />
        </div>
        <SearchBar onLocationSelect={flyToLocation} />
      </div>

      <div className="trajectory-container">
        <div className="trajectory-main">
          <TrajectoryToolbar
            isAddingWaypoint={isAddingWaypoint}
            setIsAddingWaypoint={setIsAddingWaypoint}
            showPath={showPath}
            setShowPath={setShowPath}
            showTerrain={showTerrain}
            setShowTerrain={setShowTerrain}
            pathInterpolation={pathInterpolation}
            setPathInterpolation={setPathInterpolation}
            viewMode={viewMode}
            setViewMode={setViewMode}
            onExport={exportTrajectory}
            onClear={() => {
              if (window.confirm('Clear all waypoints?')) {
                setWaypoints([]);
                setSelectedWaypointId(null);
              }
            }}
          />

          <div className="cesium-container">
            <Viewer
              ref={viewerRef}
              full
              terrainProvider={showTerrain ? createWorldTerrain() : null}
              homeButton={false}
              sceneModePicker={true}
              baseLayerPicker={true}
              navigationHelpButton={false}
              animation={false}
              timeline={false}
              fullscreenButton={true}
              vrButton={false}
              geocoder={false}
              selectionIndicator={false}
              infoBox={false}
              scene3DOnly={false}
              shouldAnimate={true}
            >
              {/* Render waypoints */}
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
                    pixelSize={selectedWaypointId === waypoint.id ? 20 : 15}
                    color={
                      selectedWaypointId === waypoint.id
                        ? Color.YELLOW
                        : index === 0 
                          ? Color.LIME
                          : index === waypoints.length - 1
                            ? Color.RED
                            : Color.CYAN
                    }
                    outlineColor={Color.BLACK}
                    outlineWidth={2}
                    heightReference={0}
                  />
                  <LabelGraphics
                    text={waypoint.name}
                    font="14pt sans-serif"
                    fillColor={Color.WHITE}
                    outlineColor={Color.BLACK}
                    outlineWidth={2}
                    pixelOffset={new Cartesian2(0, -25)}
                    verticalOrigin={VerticalOrigin.BOTTOM}
                    horizontalOrigin={HorizontalOrigin.CENTER}
                  />
                </Entity>
              ))}

              {/* Render flight path */}
              {showPath && waypoints.length > 1 && (
                <Entity>
                  <PolylineGraphics
                    positions={waypoints.map(wp =>
                      Cartesian3.fromDegrees(
                        wp.longitude,
                        wp.latitude,
                        wp.altitude
                      )
                    )}
                    width={4}
                    material={Color.LIME.withAlpha(0.8)}
                    clampToGround={false}
                  />
                </Entity>
              )}

              {/* Render ground projection */}
              {showPath && waypoints.length > 1 && (
                <Entity>
                  <PolylineGraphics
                    positions={waypoints.map(wp =>
                      Cartesian3.fromDegrees(
                        wp.longitude,
                        wp.latitude,
                        0
                      )
                    )}
                    width={2}
                    material={Color.YELLOW.withAlpha(0.5)}
                    clampToGround={true}
                  />
                </Entity>
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
          onFlyTo={(wp) => flyToLocation(wp.longitude, wp.latitude, wp.altitude + 500)}
        />
      </div>
    </div>
  );
};

export default TrajectoryPlanning;
