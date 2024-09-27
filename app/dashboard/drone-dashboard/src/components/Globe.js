// app/dashboard/drone-dashboard/src/components/Globe.js
import React, { useState, useEffect, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Html, useTexture, Stars } from '@react-three/drei';
import { Color } from 'three';
import { getElevation, llaToLocal } from '../utilities/utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import { TEXTURE_REPEAT, WORLD_SIZE } from '../utilities/utilities';
import useElevation from '../useElevation';
import '../styles/Globe.css';

// Timeout Promise for fetch operations
const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));

// Loading Spinner Component
const LoadingSpinner = () => (
  <div className="loading-container">
    <div className="spinner"></div>
    <div className="loading-message">Waiting for drones to connect...</div>
  </div>
);

// Tooltip for drones
const DroneTooltip = ({ hw_ID, state, follow_mode, altitude, opacity }) => (
  <div
    className="drone-tooltip"
    style={{
      opacity: opacity,
      transition: 'opacity 0.3s',
    }}
  >
    <ul className="tooltip-list">
      <li><strong>HW_ID:</strong> {hw_ID}</li>
      <li><strong>State:</strong> {state}</li>
      <li><strong>Mode:</strong> {follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}</li>
      <li><strong>Altitude:</strong> {altitude.toFixed(1)}m</li>
    </ul>
  </div>
);

// Drone component
const Drone = ({ position, hw_ID, state, follow_mode, altitude }) => {
  const [isHovered, setIsHovered] = useState(false);
  const [opacity, setOpacity] = useState(0);

  useEffect(() => {
    if (isHovered) {
      setOpacity(1);
    } else {
      const timeout = setTimeout(() => setOpacity(0), 150);
      return () => clearTimeout(timeout);
    }
  }, [isHovered]);

  return (
    <mesh
      position={position}
      onPointerOver={(e) => { e.stopPropagation(); setIsHovered(true); }}
      onPointerOut={(e) => setIsHovered(false)}
    >
      <sphereGeometry args={[0.5, 16, 16]} />
      <meshStandardMaterial
        color={isHovered ? new Color('#FF9800') : new Color('#2196F3')}
        emissive={isHovered ? new Color('#FF9800') : new Color('#2196F3')}
        emissiveIntensity={0.6}
        metalness={0.5}
        roughness={0.3}
      />
      <Html>
        <DroneTooltip hw_ID={hw_ID} state={state} follow_mode={follow_mode} altitude={altitude} opacity={opacity} />
      </Html>
    </mesh>
  );
};

const MemoizedDrone = React.memo(Drone);

// Custom Camera Controls for Responsive Design
const CustomOrbitControls = () => {
  const { camera, gl } = useThree();
  const controlsRef = useRef();
  
  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableDamping = true;
      controlsRef.current.dampingFactor = 0.1;
      controlsRef.current.minDistance = 5;
      controlsRef.current.maxDistance = 50;
    }
  }, []);

  return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
};

// Main Globe component
export default function Globe({ drones }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(true);
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const realElevation = useElevation(referencePoint ? referencePoint[0] : null, referencePoint ? referencePoint[1] : null);
  const [groundLevel, setGroundLevel] = useState(0);

  const handleGetTerrainClick = () => {
    if (realElevation !== null) {
      setGroundLevel(realElevation);
    }
  };

  const toggleFullscreen = () => {
    const element = document.getElementById("scene-container");

    if (!document.fullscreenElement) {
      if (element.requestFullscreen) {
        element.requestFullscreen();
      }
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  };

  useEffect(() => {
    if (referencePoint && groundLevel !== referencePoint[2]) {
      setReferencePoint([referencePoint[0], referencePoint[1], groundLevel]);
    }
  }, [groundLevel, referencePoint]);

  useEffect(() => {
    const setInitialReferencePoint = async () => {
      if (drones?.length) {
        setIsLoading(true);

        if (drones?.length && !referencePoint) {
          const avgLat = drones.reduce((sum, drone) => sum + drone.position[0], 0) / drones.length;
          const avgLon = drones.reduce((sum, drone) => sum + drone.position[1], 0) / drones.length;
          const avgAlt = drones.reduce((sum, drone) => sum + drone.position[2], 0) / drones.length;

          const elevation = await Promise.race([getElevation(avgLat, avgLon), timeoutPromise(5000)]);
          const localReference = [avgLat, avgLon, elevation ?? avgAlt];
          setReferencePoint(localReference);

          if (groundLevel === 0) {
            setGroundLevel(elevation ?? avgAlt);
          }
        }

        // Update the droneVisibility state based on the new drones list
        const newDroneVisibility = {};
        drones.forEach(drone => {
          if (droneVisibility[drone.hw_ID] !== undefined) {
            // Keep existing visibility status if drone already exists
            newDroneVisibility[drone.hw_ID] = droneVisibility[drone.hw_ID];
          } else {
            // Otherwise, set new drone to be visible
            newDroneVisibility[drone.hw_ID] = true;
          }
        });
        setDroneVisibility(newDroneVisibility);

        setIsLoading(false);
      }
    };

    setInitialReferencePoint();
  }, [drones, referencePoint]);

  useEffect(() => {
    if (referencePoint && groundLevel !== null) {
      setReferencePoint([referencePoint[0], referencePoint[1], groundLevel]);
    }
  }, [groundLevel]);

  if (isLoading || !drones?.length || !referencePoint) 
    return <LoadingSpinner />;

  const convertedDrones = drones.map(drone => ({
    ...drone,
    position: llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint),
  }));

  const toggleDroneVisibility = (droneId) => {
    setDroneVisibility(prevState => ({
      ...prevState,
      [droneId]: !prevState[droneId]
    }));
  };

  return (
    <div id="scene-container" className="scene-container">
      <Canvas camera={{ position: [20, 20, 20], up: [0, 1, 0] }}>
        {/* Ambient and Directional Lighting */}
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />

        {/* Stars for a better visual effect */}
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />

        {/* Environment and Ground */}
        {showGround && <Environment groundLevel={groundLevel} />}

        {/* Render Drones */}
        {convertedDrones.map(drone => (
          droneVisibility[drone.hw_ID] && <MemoizedDrone key={drone.hw_ID} {...drone} />
        ))}

        {/* Grid Helper */}
        {showGrid && <gridHelper args={[WORLD_SIZE, 100]} />}  

        {/* Custom Orbit Controls */}
        <CustomOrbitControls />
      </Canvas>

      {/* Toolbox and Fullscreen Buttons */}
      <div 
        className="toolbox-button"
        onClick={() => setIsToolboxOpen(!isToolboxOpen)}
        title="Toggle Control Panel"
      >
        🛠️
      </div>
      <div 
        className="fullscreen-button"
        onClick={toggleFullscreen}
        title="Toggle Fullscreen"
      >
        ⛶
      </div>

      {/* Control Panel */}
      <GlobeControlBox
        setShowGround={setShowGround}
        showGround={showGround}
        setGroundLevel={setGroundLevel}
        groundLevel={groundLevel}
        toggleDroneVisibility={toggleDroneVisibility}
        droneVisibility={droneVisibility}
        isToolboxOpen={isToolboxOpen}
        showGrid={showGrid}
        setShowGrid={setShowGrid}
        handleGetTerrainClick={handleGetTerrainClick}
      />
    </div>
  );
}
