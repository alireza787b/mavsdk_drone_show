import React, { useState, useEffect, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { OrbitControls, Html, Stars } from '@react-three/drei';
import { Color, Vector3 } from 'three';
import { getElevation, llaToLocal, calculateDistance } from '../utilities/utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import { WORLD_SIZE } from '../utilities/utilities';
import useElevation from '../useElevation';
import '../styles/Globe.css';

// Utility for promised-based timeout
const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));

// Enhanced position debugging component
const DebugLines = ({ position, color = "red" }) => (
  <group>
    <line>
      <bufferGeometry attach="geometry" setFromPoints={[
        new Vector3(position[0], 0, position[2]),
        new Vector3(...position)
      ]} />
      <lineBasicMaterial attach="material" color={color} />
    </line>
    <mesh position={[position[0], 0, position[2]]}>
      <sphereGeometry args={[0.1, 8, 8]} />
      <meshBasicMaterial color={color} />
    </mesh>
  </group>
);

// Enhanced drone tooltip component
const DroneTooltip = ({ hw_ID, state, follow_mode, altitude, position, originalPosition }) => (
  <div className="drone-tooltip">
    <ul className="tooltip-list">
      <li><strong>HW_ID:</strong> {hw_ID}</li>
      <li><strong>State:</strong> {state}</li>
      <li><strong>Mode:</strong> {follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}</li>
      <li><strong>Altitude:</strong> {altitude.toFixed(1)}m</li>
      <li>
        <strong>Original (LLA):</strong><br/>
        Lat: {originalPosition[0].toFixed(6)}<br/>
        Lon: {originalPosition[1].toFixed(6)}<br/>
        Alt: {originalPosition[2].toFixed(1)}
      </li>
      <li>
        <strong>Local (ENU):</strong><br/>
        E: {position[0].toFixed(2)}<br/>
        U: {position[1].toFixed(2)}<br/>
        N: {position[2].toFixed(2)}
      </li>
    </ul>
  </div>
);

// Enhanced drone component with debug features
const Drone = ({ position, hw_ID, state, follow_mode, altitude, originalPosition, showDebug = true }) => {
  const [isHovered, setIsHovered] = useState(false);
  const positionRef = useRef(new Vector3(...position));
  const prevPositionRef = useRef(position);

  useEffect(() => {
    if (!Vector3.arraysEqual(prevPositionRef.current, position)) {
      console.group(`Drone ${hw_ID} Position Update`);
      console.log('Previous position:', prevPositionRef.current);
      console.log('New position:', position);
      console.log('Movement delta:', {
        dx: position[0] - prevPositionRef.current[0],
        dy: position[1] - prevPositionRef.current[1],
        dz: position[2] - prevPositionRef.current[2]
      });
      console.groupEnd();
      
      prevPositionRef.current = position;
    }
  }, [position, hw_ID]);

  return (
    <group>
      <mesh
        position={position}
        onPointerOver={(e) => { e.stopPropagation(); setIsHovered(true); }}
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
        {isHovered && (
          <Html>
            <DroneTooltip
              hw_ID={hw_ID}
              state={state}
              follow_mode={follow_mode}
              altitude={altitude}
              position={position}
              originalPosition={originalPosition}
            />
          </Html>
        )}
      </mesh>
      {showDebug && <DebugLines position={position} />}
    </group>
  );
};

// Custom OrbitControls with enhanced camera handling
const CustomOrbitControls = ({ targetPosition, controlsRef }) => {
  const { camera, gl } = useThree();

  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableDamping = true;
      controlsRef.current.dampingFactor = 0.1;
      controlsRef.current.minDistance = 5;
      controlsRef.current.maxDistance = 500;
      
      if (!Vector3.arraysEqual(controlsRef.current.target.toArray(), targetPosition)) {
        controlsRef.current.target.set(...targetPosition);
        controlsRef.current.update();
      }
    }
  }, [targetPosition]);

  return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
};

// Loading spinner component
const LoadingSpinner = () => (
  <div className="loading-container">
    <div className="spinner"></div>
    <div className="loading-message">Initializing scene...</div>
  </div>
);

// Main Globe component
export default function Globe({ drones }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(false);
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [showDebugVisuals, setShowDebugVisuals] = useState(true);
  const realElevation = useElevation(
    referencePoint ? referencePoint[0] : null,
    referencePoint ? referencePoint[1] : null
  );
  const [groundLevel, setGroundLevel] = useState(0);
  const [targetPosition, setTargetPosition] = useState([0, 0, 0]);
  const controlsRef = useRef();
  const previousDronesRef = useRef([]);

  // Initialize reference point and ground level
  useEffect(() => {
    if (drones?.length && !referencePoint) {
      const initializeScene = async () => {
        try {
          // Calculate average position for reference point
          const avgLat = drones.reduce((sum, drone) => sum + drone.position[0], 0) / drones.length;
          const avgLon = drones.reduce((sum, drone) => sum + drone.position[1], 0) / drones.length;
          const avgAlt = drones.reduce((sum, drone) => sum + drone.position[2], 0) / drones.length;

          console.log('Initializing reference point:', { avgLat, avgLon, avgAlt });

          // Get ground elevation
          const elevation = await Promise.race([
            getElevation(avgLat, avgLon),
            timeoutPromise(5000)
          ]);

          const localReference = [avgLat, avgLon, elevation ?? avgAlt];
          console.log('Setting reference point:', localReference);
          
          setReferencePoint(localReference);
          setGroundLevel(elevation ?? avgAlt);
          setIsLoading(false);
        } catch (error) {
          console.error('Error initializing scene:', error);
          setIsLoading(false);
        }
      };

      initializeScene();
    }
  }, [drones]);

  // Update drone visibility state
  useEffect(() => {
    if (drones?.length) {
      setDroneVisibility(prevState => {
        const newState = { ...prevState };
        drones.forEach(drone => {
          if (newState[drone.hw_ID] === undefined) {
            newState[drone.hw_ID] = true;
          }
        });
        return newState;
      });
    }
  }, [drones]);

  // Update reference point when ground level changes
  useEffect(() => {
    if (referencePoint && groundLevel !== null && groundLevel !== referencePoint[2]) {
      setReferencePoint([referencePoint[0], referencePoint[1], groundLevel]);
    }
  }, [groundLevel]);

  // Track and log drone position changes
  useEffect(() => {
    if (drones?.length && referencePoint) {
      const convertedPositions = drones.map(drone => {
        const pos = llaToLocal(
          drone.position[0],
          drone.position[1],
          drone.position[2],
          referencePoint
        );
        return { id: drone.hw_ID, position: pos, original: drone.position };
      });

      // Log position changes
      convertedPositions.forEach(({ id, position, original }) => {
        const previousDrone = previousDronesRef.current.find(d => d.id === id);
        if (previousDrone) {
          const movement = {
            east: position[0] - previousDrone.position[0],
            up: position[1] - previousDrone.position[1],
            north: position[2] - previousDrone.position[2]
          };

          if (Object.values(movement).some(v => Math.abs(v) > 0.01)) {
            console.log(`Drone ${id} movement:`, movement);
          }
        }
      });

      previousDronesRef.current = convertedPositions;

      // Update target position for camera
      const avgPos = convertedPositions.reduce(
        (acc, { position }) => position.map((v, i) => acc[i] + v),
        [0, 0, 0]
      ).map(v => v / convertedPositions.length);

      setTargetPosition(avgPos);
    }
  }, [drones, referencePoint]);

  // UI control handlers
  const toggleFullscreen = () => {
    const element = document.getElementById("scene-container");
    if (!document.fullscreenElement) {
      element.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  };

  const focusOnDrones = () => {
    if (!drones?.length || !referencePoint) return;

    const convertedPositions = drones.map(drone =>
      llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint)
    );

    const center = convertedPositions.reduce(
      (acc, pos) => pos.map((v, i) => acc[i] + v),
      [0, 0, 0]
    ).map(v => v / convertedPositions.length);

    const maxDistance = Math.max(
      ...convertedPositions.map(pos =>
        Math.sqrt(
          pos.reduce((sum, v, i) => sum + Math.pow(v - center[i], 2), 0)
        )
      )
    );

    setTargetPosition(center);

    if (controlsRef.current?.object) {
      const camera = controlsRef.current.object;
      const offset = maxDistance * 2 + 10;
      camera.position.set(
        center[0] + offset,
        center[1] + offset,
        center[2] + offset
      );
      camera.updateProjectionMatrix();
      controlsRef.current.update();
    }
  };

  if (isLoading || !referencePoint) {
    return <LoadingSpinner />;
  }

  const convertedDrones = drones.map(drone => ({
    ...drone,
    originalPosition: drone.position,
    position: llaToLocal(
      drone.position[0],
      drone.position[1],
      drone.position[2],
      referencePoint
    ),
  }));

  return (
    <div id="scene-container" className="scene-container">
      <Canvas camera={{ position: [20, 20, 20], up: [0, 1, 0] }}>
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />
        
        {showGround && <Environment groundLevel={groundLevel} />}
        
        {convertedDrones.map(drone => (
          droneVisibility[drone.hw_ID] && (
            <Drone
              key={drone.hw_ID}
              {...drone}
              showDebug={showDebugVisuals}
            />
          )
        ))}
        
        {showGrid && <gridHelper args={[WORLD_SIZE, 100]} />}
        
        <CustomOrbitControls
          targetPosition={targetPosition}
          controlsRef={controlsRef}
        />
      </Canvas>

      <div className="button-container">
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
        <div
          className="debug-button"
          onClick={() => setShowDebugVisuals(!showDebugVisuals)}
          title="Toggle Debug Visuals"
        >
          🔍
        </div>
        <div
          className="toolbox-button"
          onClick={() => setIsToolboxOpen(!isToolboxOpen)}
          title="Toggle Control Panel"
        >
          🛠️
        </div>
      </div>

      <GlobeControlBox
        setShowGround={setShowGround}
        showGround={showGround}
        setGroundLevel={setGroundLevel}
        groundLevel={groundLevel}
        toggleDroneVisibility={id => setDroneVisibility(prev => ({
          ...prev,
          [id]: !prev[id]
        }))}
        droneVisibility={droneVisibility}
        isToolboxOpen={isToolboxOpen}
        showGrid={showGrid}
        setShowGrid={setShowGrid}
        handleGetTerrainClick={() => realElevation !== null && setGroundLevel(realElevation)}
        showDebugVisuals={showDebugVisuals}
        setShowDebugVisuals={setShowDebugVisuals}
      />
    </div>
  );
}