import React, { useState, useEffect, useRef } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import PropTypes from 'prop-types';
import { OrbitControls, Html, Stars } from '@react-three/drei';
import { Color } from 'three';
import { getElevation, llaToLocal } from '../utilities/utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import { WORLD_SIZE } from '../utilities/utilities';
import useElevation from '../useElevation';
import '../styles/Globe.css';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';

const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));

const LoadingSpinner = () => (
  <div className="loading-container">
    <div className="spinner"></div>
    <div className="loading-message">Waiting for drones to connect...</div>
  </div>
);
const DroneTooltip = ({ hw_id, pos_id, state, follow_mode, altitude, opacity, localPosition }) => (
  <div
    className="drone-tooltip"
    style={{
      opacity: opacity,
      transition: 'opacity 0.3s',
    }}
  >
    <ul className="tooltip-list">
      <li><strong>ID:</strong> {formatCompactDroneIdentity(pos_id, hw_id, `H${hw_id}`)}</li>
      <li><strong>State:</strong> {state}</li>
      <li><strong>Mode:</strong> {follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}</li>
      <li><strong>Altitude:</strong> {altitude.toFixed(1)}m</li>
      <li><strong>Local Position:</strong> [{localPosition[0].toFixed(2)}, {localPosition[1].toFixed(2)}, {localPosition[2].toFixed(2)}]</li>
    </ul>
  </div>
);

const Drone = ({ position, hw_id, pos_id, state, follow_mode, altitude }) => {
  const [isHovered, setIsHovered] = useState(false);
  const [opacity, setOpacity] = useState(0);

  useEffect(() => {
    if (isHovered) {
      setOpacity(1);
    } else {
      const timeout = setTimeout(() => setOpacity(0), 150);
      return () => clearTimeout(timeout);
    }
  }, [isHovered, position, hw_id]);

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
        <DroneTooltip
          hw_id={hw_id}
          pos_id={pos_id}
          state={state}
          follow_mode={follow_mode}
          altitude={altitude}
          opacity={opacity}
          localPosition={position}
        />
      </Html>
    </mesh>
  );
};

Drone.propTypes = {
  position: PropTypes.arrayOf(PropTypes.number).isRequired,
  hw_id: PropTypes.string.isRequired,
  pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  state: PropTypes.string.isRequired,
  follow_mode: PropTypes.number.isRequired,
  altitude: PropTypes.number.isRequired,
};

const MemoizedDrone = React.memo(Drone);



const CustomOrbitControls = ({ targetPosition, controlsRef }) => {
  const { camera, gl } = useThree();

  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableDamping = true;
      controlsRef.current.dampingFactor = 0.1;
      controlsRef.current.minDistance = 5;
      controlsRef.current.maxDistance = 500;
      controlsRef.current.target.set(...targetPosition);
      controlsRef.current.update();
    }
  }, [targetPosition, camera, controlsRef]);

  return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
};


CustomOrbitControls.propTypes = {
  targetPosition: PropTypes.arrayOf(PropTypes.number).isRequired,
  controlsRef: PropTypes.object.isRequired,
};

export default function Globe({ drones }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(false);
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const realElevation = useElevation(referencePoint ? referencePoint[0] : null, referencePoint ? referencePoint[1] : null);
  const [groundLevel, setGroundLevel] = useState(0);
  const [targetPosition, setTargetPosition] = useState([0, 0, 0]);
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

  // Set reference point once when drones first connect — elevation is fetched once
  // and cached. The effect skips when referencePoint is already set.
  const hasDrones = drones?.length > 0;
  useEffect(() => {
    if (!hasDrones || referencePoint) return;

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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only run when drones first arrive; referencePoint guard prevents re-fetch
  }, [hasDrones]);

  useEffect(() => {
    if (drones?.length) {
      const newDroneVisibility = {};
      drones.forEach(drone => {
        newDroneVisibility[drone[FIELD_NAMES.HW_ID]] = droneVisibility[drone[FIELD_NAMES.HW_ID]] ?? true;
      });
      setDroneVisibility(newDroneVisibility);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally omit droneVisibility to avoid infinite loop
  }, [drones]);

  useEffect(() => {
    setReferencePoint(prev => {
      if (prev && groundLevel !== null && groundLevel !== prev[2]) {
        return [prev[0], prev[1], groundLevel];
      }
      return prev;
    });
  }, [groundLevel]);

  useEffect(() => {
    if (drones?.length && referencePoint) {
      const convertedPositions = drones.map(drone => llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint));

      const avgX = convertedPositions.reduce((sum, pos) => sum + pos[0], 0) / convertedPositions.length;
      const avgY = convertedPositions.reduce((sum, pos) => sum + pos[1], 0) / convertedPositions.length;
      const avgZ = convertedPositions.reduce((sum, pos) => sum + pos[2], 0) / convertedPositions.length;

      setTargetPosition([avgX, avgY, avgZ]);
    }
  }, [drones, referencePoint]);

  const focusOnDrones = () => {
    if (drones?.length && referencePoint) {
      const convertedPositions = drones.map(drone => llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint));
      const avgX = convertedPositions.reduce((sum, pos) => sum + pos[0], 0) / convertedPositions.length;
      const avgY = convertedPositions.reduce((sum, pos) => sum + pos[1], 0) / convertedPositions.length;
      const avgZ = convertedPositions.reduce((sum, pos) => sum + pos[2], 0) / convertedPositions.length;

      const center = [avgX, avgY, avgZ];

      let maxDistance = 0;
      convertedPositions.forEach(pos => {
        const dx = pos[0] - center[0];
        const dy = pos[1] - center[1];
        const dz = pos[2] - center[2];
        const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (distance > maxDistance) {
          maxDistance = distance;
        }
      });

      setTargetPosition(center);

      if (controlsRef.current && controlsRef.current.object) {
        const camera = controlsRef.current.object;
        const offset = maxDistance * 2 + 10;
        camera.position.set(center[0] + offset, center[1] + offset, center[2] + offset);
        camera.updateProjectionMatrix();
        controlsRef.current.update();
      }
    }
  };

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

  return (
    <div id="scene-container" className="scene-container">
      <Canvas camera={{ position: [20, 20, 20], up: [0, 1, 0] }}>
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />
        <axesHelper args={[50]} />
        {showGround && <Environment groundLevel={groundLevel} />}
        {convertedDrones.map(drone => (
          droneVisibility[drone[FIELD_NAMES.HW_ID]] && <MemoizedDrone key={drone[FIELD_NAMES.HW_ID]} {...drone} />
        ))}
        {showGrid && <gridHelper args={[WORLD_SIZE, 100]} />}
        <CustomOrbitControls targetPosition={targetPosition} controlsRef={controlsRef} />

      </Canvas>

      {/* Render Compass outside the Canvas */}
      
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

Globe.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string.isRequired,
    pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    position: PropTypes.arrayOf(PropTypes.number).isRequired,
    state: PropTypes.string,
    follow_mode: PropTypes.number,
    altitude: PropTypes.number,
  })).isRequired,
};
