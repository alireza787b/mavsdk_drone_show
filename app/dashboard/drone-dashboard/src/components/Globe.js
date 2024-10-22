// app/dashboard/drone-dashboard/src/components/Globe.js
import React, { useState, useEffect, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Html, Stars } from '@react-three/drei';
import { Color } from 'three';
import { getElevation, llaToLocal } from '../utilities/utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import { WORLD_SIZE } from '../utilities/utilities';
import useElevation from '../useElevation';
import '../styles/Globe.css';

const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));

const LoadingSpinner = () => (
  <div className="loading-container">
    <div className="spinner"></div>
    <div className="loading-message">Waiting for drones to connect...</div>
  </div>
);

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

export default function Globe({ drones }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(false); // Hide ground by default
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const realElevation = useElevation(referencePoint ? referencePoint[0] : null, referencePoint ? referencePoint[1] : null);
  const [groundLevel, setGroundLevel] = useState(0);

  const controlsRef = useRef();

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

  // Initial setup of reference point
  useEffect(() => {
    if (drones?.length && !referencePoint) {
      setIsLoading(true);
      const setReferencePointAsync = async () => {
        const avgLat = drones.reduce((sum, drone) => sum + drone.position[0], 0) / drones.length;
        const avgLon = drones.reduce((sum, drone) => sum + drone.position[1], 0) / drones.length;
        const avgAlt = drones.reduce((sum, drone) => sum + drone.position[2], 0) / drones.length;

        const elevation = await Promise.race([getElevation(avgLat, avgLon), timeoutPromise(5000)]);
        const localReference = [avgLat, avgLon, elevation ?? avgAlt];
        setReferencePoint(localReference);

        if (groundLevel === 0) {
          setGroundLevel(elevation ?? avgAlt);
        }
        setIsLoading(false);
      };
      setReferencePointAsync();
    }
  }, [drones, referencePoint]);

  // Update drone visibility when drones change
  useEffect(() => {
    if (drones?.length) {
      const newDroneVisibility = {};
      drones.forEach(drone => {
        newDroneVisibility[drone.hw_ID] = droneVisibility[drone.hw_ID] ?? true;
      });
      setDroneVisibility(newDroneVisibility);
    }
  }, [drones]);

  useEffect(() => {
    if (referencePoint && groundLevel !== null && groundLevel !== referencePoint[2]) {
      setReferencePoint([referencePoint[0], referencePoint[1], groundLevel]);
    }
  }, [groundLevel]);

  if (isLoading || !referencePoint) {
    return <LoadingSpinner />;
  }

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

  // Function to focus the camera on the drones
  const focusOnDrones = () => {
    if (controlsRef.current && convertedDrones.length > 0) {
      const positions = convertedDrones.map(drone => drone.position);
      // Calculate the center
      const center = positions.reduce((acc, pos) => {
        return [acc[0] + pos[0], acc[1] + pos[1], acc[2] + pos[2]];
      }, [0, 0, 0]).map(coord => coord / positions.length);

      // Calculate the maximum distance from the center
      const distances = positions.map(pos => {
        const dx = pos[0] - center[0];
        const dy = pos[1] - center[1];
        const dz = pos[2] - center[2];
        return Math.sqrt(dx * dx + dy * dy + dz * dz);
      });
      const maxDistance = Math.max(...distances);

      // Adjust camera position
      const cameraDistance = maxDistance * 2 || 10; // Default to 10 if maxDistance is 0
      const camera = controlsRef.current.object;
      camera.position.set(
        center[0] + cameraDistance,
        center[1] + cameraDistance,
        center[2] + cameraDistance
      );

      // Update controls target
      controlsRef.current.target.set(center[0], center[1], center[2]);
      controlsRef.current.update();
    }
  };

  // Focus on drones upon initialization or when drones update
  useEffect(() => {
    if (convertedDrones.length > 0 && controlsRef.current) {
      focusOnDrones();
    }
  }, [convertedDrones]);

  // Custom Camera Controls
  const CustomOrbitControls = () => {
    const { camera, gl } = useThree();

    useEffect(() => {
      if (controlsRef.current) {
        controlsRef.current.enableDamping = true;
        controlsRef.current.dampingFactor = 0.1;
        controlsRef.current.minDistance = 5;
        controlsRef.current.maxDistance = 5000;
      }
    }, []);

    return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
  };

  return (
    <div id="scene-container" className="scene-container">
      <Canvas camera={{ position: [0, 0, 10], up: [0, 1, 0] }}>
        {/* Ambient and Directional Lighting */}
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />

        {/* Stars for a better visual effect */}
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />

        {/* Environment and Ground */}
        {showGround && <Environment groundLevel={groundLevel} opacity={0.5} />}

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
      <div 
        className="focus-button"
        onClick={focusOnDrones}
        title="Focus on Drones"
      >
        🎯
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
