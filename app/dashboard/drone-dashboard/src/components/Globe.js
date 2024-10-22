// src/components/Globe.js
import React, { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
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
      <li>
        <strong>HW_ID:</strong> {hw_ID}
      </li>
      <li>
        <strong>State:</strong> {state}
      </li>
      <li>
        <strong>Mode:</strong> {follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}
      </li>
      <li>
        <strong>Altitude:</strong> {altitude.toFixed(1)}m
      </li>
    </ul>
  </div>
);

const Drone = React.memo(({ position, hw_ID, state, follow_mode, altitude }) => {
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
      onPointerOver={(e) => {
        e.stopPropagation();
        setIsHovered(true);
      }}
      onPointerOut={() => setIsHovered(false)}
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
        <DroneTooltip
          hw_ID={hw_ID}
          state={state}
          follow_mode={follow_mode}
          altitude={altitude}
          opacity={opacity}
        />
      </Html>
    </mesh>
  );
});

const CustomOrbitControls = ({ controlsRef }) => {
  const { camera, gl } = useThree();

  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableDamping = true;
      controlsRef.current.dampingFactor = 0.1;
      controlsRef.current.minDistance = 5;
      controlsRef.current.maxDistance = 500;
    }
  }, [controlsRef]);

  return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
};

export default function Globe({ drones }) {
  // State and Ref Declarations
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(false); // Default to false
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const controlsRef = useRef();
  const [hasFocused, setHasFocused] = useState(false);

  // Custom Hook
  const realElevation = useElevation(
    referencePoint ? referencePoint[0] : null,
    referencePoint ? referencePoint[1] : null
  );
  const [groundLevel, setGroundLevel] = useState(0);

  // Data Transformation
  const convertedDrones = useMemo(() => {
    if (!referencePoint) return [];
    return drones.map((drone) => ({
      ...drone,
      position: llaToLocal(
        drone.position[0],
        drone.position[1],
        drone.position[2],
        referencePoint
      ),
    }));
  }, [drones, referencePoint]);

  // Handlers and Utilities
  const handleGetTerrainClick = () => {
    if (realElevation !== null) {
      setGroundLevel(realElevation);
    }
  };

  const toggleFullscreen = () => {
    const element = document.getElementById('scene-container');

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

  const toggleDroneVisibility = (droneId) => {
    setDroneVisibility((prevState) => ({
      ...prevState,
      [droneId]: !prevState[droneId],
    }));
  };

  const computeDronesCenter = useCallback((drones) => {
    if (drones.length === 0) return [0, 0, 0];
    const sum = drones.reduce(
      (acc, drone) => {
        acc.x += drone.position[0];
        acc.y += drone.position[1];
        acc.z += drone.position[2];
        return acc;
      },
      { x: 0, y: 0, z: 0 }
    );
    return [sum.x / drones.length, sum.y / drones.length, sum.z / drones.length];
  }, []);

  const focusOnDrones = useCallback(() => {
    if (controlsRef.current && convertedDrones.length > 0) {
      const dronesCenter = computeDronesCenter(convertedDrones);

      // Calculate the maximum distance from the center to any drone
      const maxDistance = Math.max(
        ...convertedDrones.map((drone) => {
          const dx = drone.position[0] - dronesCenter[0];
          const dy = drone.position[1] - dronesCenter[1];
          const dz = drone.position[2] - dronesCenter[2];
          return Math.sqrt(dx * dx + dy * dy + dz * dz);
        })
      );

      // Set camera position relative to the drones' center
      const cameraDistance = maxDistance * 2 + 10; // Adjust multiplier as needed
      controlsRef.current.object.position.set(
        dronesCenter[0] + cameraDistance,
        dronesCenter[1] + cameraDistance,
        dronesCenter[2] + cameraDistance
      );
      controlsRef.current.target.set(...dronesCenter);
      controlsRef.current.update();
    }
  }, [controlsRef, convertedDrones, computeDronesCenter]);

  // Hooks
  useEffect(() => {
    // Initial setup of reference point
    if (drones?.length && !referencePoint) {
      setIsLoading(true);
      const setReferencePointAsync = async () => {
        const avgLat = drones.reduce((sum, drone) => sum + drone.position[0], 0) / drones.length;
        const avgLon = drones.reduce((sum, drone) => sum + drone.position[1], 0) / drones.length;
        const avgAlt = drones.reduce((sum, drone) => sum + drone.position[2], 0) / drones.length;

        const elevation = await Promise.race([getElevation(avgLat, avgLon), timeoutPromise(5000)]);
        const localReference = [avgLat, avgLon, 0]; // Set altitude to 0
        setReferencePoint(localReference);

        if (groundLevel === 0) {
          setGroundLevel(elevation ?? avgAlt);
        }
        setIsLoading(false);
      };
      setReferencePointAsync();
    }
  }, [drones, referencePoint, groundLevel]);

  useEffect(() => {
    // Update drone visibility when drones change
    if (drones?.length) {
      const newDroneVisibility = {};
      drones.forEach((drone) => {
        newDroneVisibility[drone.hw_ID] = droneVisibility[drone.hw_ID] ?? true;
      });
      setDroneVisibility(newDroneVisibility);
    }
  }, [drones]);

  useEffect(() => {
    // Focus on drones when the component mounts and drones are loaded
    if (!hasFocused && controlsRef.current && convertedDrones.length > 0) {
      focusOnDrones();
      setHasFocused(true);
    }
  }, [hasFocused, controlsRef, convertedDrones, focusOnDrones]);

  // Early Return if Loading
  if (isLoading || !referencePoint) {
    return <LoadingSpinner />;
  }

  return (
    <div id="scene-container" className="scene-container">
      <Canvas camera={{ position: [20, 20, 20], up: [0, 1, 0] }}>
        {/* Ambient and Directional Lighting */}
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />

        {/* Stars for a better visual effect */}
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />

        {/* Environment and Ground */}
        {showGround && <Environment />}

        {/* Render Drones */}
        {convertedDrones.map(
          (drone) =>
            droneVisibility[drone.hw_ID] && <Drone key={drone.hw_ID} {...drone} />
        )}

        {/* Grid Helper */}
        {showGrid && <gridHelper args={[WORLD_SIZE, 100]} />}

        {/* Custom Orbit Controls */}
        <CustomOrbitControls controlsRef={controlsRef} />
      </Canvas>

      {/* Control Icons */}
      <div className="control-icons">
        <div
          className="focus-button"
          onClick={focusOnDrones}
          title="Focus on Drones"
        >
          🎯
        </div>
        <div
          className="fullscreen-button"
          onClick={toggleFullscreen}
          title="Toggle Fullscreen"
        >
          ⛶
        </div>
        <div
          className="toolbox-button"
          onClick={() => setIsToolboxOpen(!isToolboxOpen)}
          title="Toggle Control Panel"
        >
          🛠️
        </div>
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
