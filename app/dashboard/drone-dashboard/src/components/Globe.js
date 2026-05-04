import React, { useCallback, useState, useEffect, useRef } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import PropTypes from 'prop-types';
import { OrbitControls, Stars } from '@react-three/drei';
import { Color, Vector3 } from 'three';
import { FaCompressAlt, FaCrosshairs, FaSlidersH } from 'react-icons/fa';
import { getElevation, llaToLocal } from '../utilities/utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import TacticalDroneCard from './TacticalDroneCard';
import { WORLD_SIZE } from '../utilities/utilities';
import useElevation from '../useElevation';
import '../styles/Globe.css';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';

const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));
const DEFAULT_DRONE_MARKER_COLOR = 'dodgerblue';
const HEX_COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;
const SELECTED_CARD_WIDTH_PX = 320;
const SELECTED_CARD_HEIGHT_PX = 260;
const SELECTED_CARD_GAP_PX = 18;
const DEFAULT_CAMERA_POSITION = [12, 10, 12];
const CAMERA_FIT_PADDING = 6;
const CAMERA_FIT_SCALE = 1.32;
const MIN_CAMERA_FIT_DISTANCE = 9;

const resolveMarkerColor = (candidate, fallback = DEFAULT_DRONE_MARKER_COLOR) => {
  const normalized = String(candidate || '').trim();
  return HEX_COLOR_PATTERN.test(normalized) ? normalized : fallback;
};

const hasUsableGeoPosition = (position = []) => {
  const lat = Number(position[0]);
  const lon = Number(position[1]);
  return Number.isFinite(lat) && Number.isFinite(lon) && (Math.abs(lat) > 0.000001 || Math.abs(lon) > 0.000001);
};

const buildNoFixPosition = (index, total) => {
  const columns = Math.max(1, Math.ceil(Math.sqrt(Math.max(total, 1))));
  const row = Math.floor(index / columns);
  const col = index % columns;
  const spread = 3.2;
  return [
    (col - ((columns - 1) / 2)) * spread,
    4.6,
    -2.4 - (row * spread),
  ];
};

const buildDisplayPosition = (drone, referencePoint, noFixDrones = []) => {
  if (drone.noMapFix || !hasUsableGeoPosition(drone.position)) {
    const noFixIndex = noFixDrones.findIndex((candidate) => (
      String(candidate[FIELD_NAMES.HW_ID]) === String(drone[FIELD_NAMES.HW_ID])
    ));
    return buildNoFixPosition(noFixIndex, noFixDrones.length);
  }

  return llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint);
};

const LoadingSpinner = () => (
  <div className="loading-container">
    <div className="spinner"></div>
    <div className="loading-message">Waiting for drones to connect...</div>
  </div>
);

const SelectedDroneScreenAnchor = ({ drone, onScreenPosition }) => {
  const { camera, size } = useThree();
  const lastPositionRef = useRef(null);

  useFrame(() => {
    if (!drone?.position) {
      return;
    }

    const projected = new Vector3(...drone.position).project(camera);
    const visible = projected.z >= -1 && projected.z <= 1;
    const next = {
      x: (projected.x * 0.5 + 0.5) * size.width,
      y: (-projected.y * 0.5 + 0.5) * size.height,
      width: size.width,
      height: size.height,
      visible,
    };
    const previous = lastPositionRef.current;
    if (
      !previous
      || Math.abs(previous.x - next.x) > 2
      || Math.abs(previous.y - next.y) > 2
      || previous.visible !== next.visible
    ) {
      lastPositionRef.current = next;
      onScreenPosition(next);
    }
  });

  return null;
};

SelectedDroneScreenAnchor.propTypes = {
  drone: PropTypes.shape({
    position: PropTypes.arrayOf(PropTypes.number),
  }),
  onScreenPosition: PropTypes.func.isRequired,
};

const DroneScreenAnchorProjector = ({ drones, onScreenAnchors }) => {
  const { camera, size } = useThree();
  const lastPayloadRef = useRef('');
  const themeColors = getPlotThemeColors();

  useFrame(() => {
    const anchors = drones.map((drone) => {
      const projected = new Vector3(...drone.position).project(camera);
      return {
        id: String(drone[FIELD_NAMES.HW_ID]),
        label: drone.identityLabel,
        markerColor: resolveMarkerColor(drone.marker_color, themeColors.primary),
        noMapFix: drone.noMapFix,
        runtimeClass: drone.runtime_indicator_class || drone.runtimeStatus?.indicatorClass || 'unknown',
        x: Math.round((projected.x * 0.5 + 0.5) * size.width),
        y: Math.round((-projected.y * 0.5 + 0.5) * size.height),
        visible: projected.z >= -1 && projected.z <= 1,
      };
    });
    const payload = JSON.stringify(anchors);
    if (payload !== lastPayloadRef.current) {
      lastPayloadRef.current = payload;
      onScreenAnchors(anchors);
    }
  });

  return null;
};

DroneScreenAnchorProjector.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string,
    identityLabel: PropTypes.string,
    marker_color: PropTypes.string,
    noMapFix: PropTypes.bool,
    runtime_indicator_class: PropTypes.string,
    runtimeStatus: PropTypes.object,
    position: PropTypes.arrayOf(PropTypes.number),
  })).isRequired,
  onScreenAnchors: PropTypes.func.isRequired,
};

const resolveSelectedCardPlacement = (screenPosition) => {
  const x = screenPosition?.x ?? 24;
  const y = screenPosition?.y ?? 24;
  const width = screenPosition?.width ?? 0;
  const height = screenPosition?.height ?? 0;
  const placeLeft = width > 0 && x > width - SELECTED_CARD_WIDTH_PX - 48;
  const placeAbove = height > 0 && y > height * 0.38;
  const rawLeft = Math.round(
    placeLeft ? x - SELECTED_CARD_WIDTH_PX - SELECTED_CARD_GAP_PX : x + SELECTED_CARD_GAP_PX
  );
  const rawTop = Math.round(
    placeAbove ? y - SELECTED_CARD_HEIGHT_PX - SELECTED_CARD_GAP_PX : y - 16
  );

  return {
    placeLeft,
    placeAbove,
    style: {
      left: `min(max(${rawLeft}px, 12px), calc(100% - ${SELECTED_CARD_WIDTH_PX}px))`,
      top: `min(max(${rawTop}px, 12px), calc(100% - ${SELECTED_CARD_HEIGHT_PX}px))`,
    },
  };
};
const Drone = ({
  position,
  hw_id,
  marker_color,
  noMapFix,
  runtime_indicator_class,
  selected,
  onSelect,
}) => {
  const [isHovered, setIsHovered] = useState(false);
  const meshRef = useRef(null);
  const targetPositionRef = useRef(new Vector3(...position));
  const hasInitialPositionRef = useRef(false);
  const themeColors = getPlotThemeColors();
  const normalColor = new Color(resolveMarkerColor(marker_color, themeColors.primary));
  const hoverColor = new Color(themeColors.warning);
  const active = selected || isHovered;
  const markerRadius = noMapFix ? 0.54 : 0.64;
  const linkDimmed = ['offline', 'never-seen'].includes(runtime_indicator_class);

  useEffect(() => {
    targetPositionRef.current.set(...position);
    if (!hasInitialPositionRef.current && meshRef.current) {
      meshRef.current.position.set(...position);
      hasInitialPositionRef.current = true;
    }
  }, [position]);

  useFrame((_, delta) => {
    if (!meshRef.current) {
      return;
    }
    const alpha = 1 - Math.exp(-8 * Math.min(delta, 0.25));
    meshRef.current.position.lerp(targetPositionRef.current, alpha);
  });

  return (
    <mesh
      ref={meshRef}
      onPointerOver={(e) => { e.stopPropagation(); setIsHovered(true); }}
      onPointerOut={() => setIsHovered(false)}
      onPointerDown={(e) => {
        e.stopPropagation();
        onSelect(String(hw_id));
      }}
    >
      <sphereGeometry args={[markerRadius, 24, 24]} />
      <meshStandardMaterial
        color={active ? hoverColor : normalColor}
        emissive={active ? hoverColor : normalColor}
        emissiveIntensity={active ? 0.9 : 0.58}
        metalness={0.5}
        roughness={noMapFix ? 0.68 : 0.3}
        transparent={noMapFix || linkDimmed}
        opacity={linkDimmed ? 0.38 : noMapFix ? 0.72 : 1}
      />
      <mesh>
        <sphereGeometry args={[1.45, 16, 16]} />
        <meshBasicMaterial transparent opacity={0.01} depthWrite={false} />
      </mesh>
      {active && (
        <mesh rotation={[Math.PI / 2, 0, 0]}>
          <torusGeometry args={[noMapFix ? 0.76 : 0.86, 0.035, 10, 36]} />
          <meshStandardMaterial color={hoverColor} emissive={hoverColor} emissiveIntensity={0.9} />
        </mesh>
      )}
    </mesh>
  );
};

Drone.propTypes = {
  position: PropTypes.arrayOf(PropTypes.number).isRequired,
  hw_id: PropTypes.string.isRequired,
  marker_color: PropTypes.string,
  noMapFix: PropTypes.bool,
  runtime_indicator_class: PropTypes.string,
  selected: PropTypes.bool,
  onSelect: PropTypes.func.isRequired,
};

const MemoizedDrone = React.memo(Drone);



const CustomOrbitControls = ({ targetPosition, controlsRef }) => {
  const { camera, gl } = useThree();
  const targetVectorRef = useRef(new Vector3(...targetPosition));
  const initializedRef = useRef(false);

  useEffect(() => {
    if (controlsRef.current) {
      controlsRef.current.enableDamping = true;
      controlsRef.current.dampingFactor = 0.1;
      controlsRef.current.minDistance = 5;
      controlsRef.current.maxDistance = 500;
      controlsRef.current.update();
    }
  }, [camera, controlsRef]);

  useEffect(() => {
    targetVectorRef.current.set(...targetPosition);
  }, [targetPosition]);

  useFrame((_, delta) => {
    const controls = controlsRef.current;
    if (!controls) {
      return;
    }

    if (!initializedRef.current) {
      controls.target.set(...targetPosition);
      initializedRef.current = true;
    } else {
      const alpha = 1 - Math.exp(-2.5 * Math.min(delta, 0.25));
      controls.target.lerp(targetVectorRef.current, alpha);
    }
    controls.update();
  });

  return <OrbitControls ref={controlsRef} args={[camera, gl.domElement]} />;
};


CustomOrbitControls.propTypes = {
  targetPosition: PropTypes.arrayOf(PropTypes.number).isRequired,
  controlsRef: PropTypes.object.isRequired,
};

export default function Globe({ drones, selectedDroneId, onSelectDrone }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(false);
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);
  const [selectedScreenPosition, setSelectedScreenPosition] = useState(null);
  const [screenAnchors, setScreenAnchors] = useState([]);
  const realElevation = useElevation(referencePoint ? referencePoint[0] : null, referencePoint ? referencePoint[1] : null);
  const [groundLevel, setGroundLevel] = useState(0);
  const [targetPosition, setTargetPosition] = useState([0, 0, 0]);
  const controlsRef = useRef();
  const didInitialCameraFitRef = useRef(false);

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
      const positionedDrones = drones.filter((drone) => !drone.noMapFix && hasUsableGeoPosition(drone.position));
      const referenceDrones = positionedDrones.length > 0 ? positionedDrones : drones;
      const avgLat = referenceDrones.reduce((sum, drone) => sum + drone.position[0], 0) / referenceDrones.length;
      const avgLon = referenceDrones.reduce((sum, drone) => sum + drone.position[1], 0) / referenceDrones.length;
      const avgAlt = referenceDrones.reduce((sum, drone) => sum + drone.position[2], 0) / referenceDrones.length;

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
      const noFixDrones = drones.filter((drone) => drone.noMapFix || !hasUsableGeoPosition(drone.position));
      const convertedPositions = drones.map((drone) => buildDisplayPosition(drone, referencePoint, noFixDrones));

      const avgX = convertedPositions.reduce((sum, pos) => sum + pos[0], 0) / convertedPositions.length;
      const avgY = convertedPositions.reduce((sum, pos) => sum + pos[1], 0) / convertedPositions.length;
      const avgZ = convertedPositions.reduce((sum, pos) => sum + pos[2], 0) / convertedPositions.length;

      setTargetPosition([avgX, avgY, avgZ]);
    }
  }, [drones, referencePoint]);

  const focusOnDrones = useCallback(() => {
    if (drones?.length && referencePoint) {
      const noFixDrones = drones.filter((drone) => drone.noMapFix || !hasUsableGeoPosition(drone.position));
      const convertedPositions = drones.map((drone) => buildDisplayPosition(drone, referencePoint, noFixDrones));
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
        const offset = Math.max(MIN_CAMERA_FIT_DISTANCE, (maxDistance * CAMERA_FIT_SCALE) + CAMERA_FIT_PADDING);
        camera.position.set(center[0] + offset, center[1] + (offset * 0.78), center[2] + offset);
        camera.updateProjectionMatrix();
        controlsRef.current.update();
      }
    }
  }, [drones, referencePoint]);

  useEffect(() => {
    if (didInitialCameraFitRef.current || isLoading || !referencePoint || !drones?.length) {
      return undefined;
    }

    didInitialCameraFitRef.current = true;
    const frameId = window.requestAnimationFrame(() => {
      focusOnDrones();
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [drones?.length, focusOnDrones, isLoading, referencePoint]);

  const handleSceneBackgroundPointerDown = useCallback((event) => {
    const target = event.target;
    if (
      target?.closest?.(
        '.globe-selected-card-popover, .globe-drone-screen-hit, .button-container, .globe-control-box'
      )
    ) {
      return;
    }

    if (isToolboxOpen) {
      setIsToolboxOpen(false);
      return;
    }

    if (!selectedDroneId) {
      return;
    }

    onSelectDrone(null);
  }, [isToolboxOpen, onSelectDrone, selectedDroneId]);

  if (isLoading || !referencePoint) {
    return <LoadingSpinner />;
  }

  const noFixDrones = drones.filter((drone) => drone.noMapFix || !hasUsableGeoPosition(drone.position));
  const convertedDrones = drones.map((drone) => {
    const noMapFix = drone.noMapFix || !hasUsableGeoPosition(drone.position);
    const displayPosition = buildDisplayPosition(drone, referencePoint, noFixDrones);
    const hwId = String(drone[FIELD_NAMES.HW_ID]);
    return {
      ...drone,
      geoPosition: drone.position,
      identityLabel: formatCompactDroneIdentity(drone[FIELD_NAMES.POS_ID], hwId, `H${hwId}`),
      noMapFix,
      position: displayPosition,
    };
  });
  const selectedDrone = convertedDrones.find(
    (drone) => String(drone[FIELD_NAMES.HW_ID]) === String(selectedDroneId || '')
  ) || null;
  const selectedCardPlacement = resolveSelectedCardPlacement(selectedScreenPosition);

  const toggleDroneVisibility = (droneId) => {
    setDroneVisibility(prevState => ({
      ...prevState,
      [droneId]: !prevState[droneId]
    }));
  };

  return (
    <div
      id="scene-container"
      className={`scene-container ${isToolboxOpen ? 'filters-open' : ''}`}
      onPointerDown={handleSceneBackgroundPointerDown}
    >
      <Canvas camera={{ position: DEFAULT_CAMERA_POSITION, up: [0, 1, 0] }}>
        <ambientLight intensity={0.3} />
        <directionalLight position={[10, 10, 5]} intensity={1} />
        <Stars radius={100} depth={50} count={5000} factor={4} saturation={0} fade />
        <axesHelper args={[50]} />
        {showGround && <Environment groundLevel={groundLevel} />}
        {convertedDrones.map(drone => (
          droneVisibility[drone[FIELD_NAMES.HW_ID]] && (
            <MemoizedDrone
              key={drone[FIELD_NAMES.HW_ID]}
              {...drone}
              selected={String(selectedDroneId || '') === String(drone[FIELD_NAMES.HW_ID])}
              onSelect={onSelectDrone}
            />
          )
        ))}
        {selectedDrone && (
          <SelectedDroneScreenAnchor
            drone={selectedDrone}
            onScreenPosition={setSelectedScreenPosition}
          />
        )}
        <DroneScreenAnchorProjector
          drones={convertedDrones.filter((drone) => droneVisibility[drone[FIELD_NAMES.HW_ID]])}
          onScreenAnchors={setScreenAnchors}
        />
        {showGrid && <gridHelper args={[WORLD_SIZE, 100]} />}
        <CustomOrbitControls targetPosition={targetPosition} controlsRef={controlsRef} />

      </Canvas>
      <div className="globe-drone-screen-targets" aria-label="3D drone touch targets">
        {screenAnchors.map((anchor) => (
          anchor.visible && (
            <button
              key={anchor.id}
              type="button"
              className={[
                'globe-drone-screen-hit',
                anchor.noMapFix ? 'no-map-fix' : '',
                anchor.runtimeClass ? `runtime-${anchor.runtimeClass}` : '',
                String(selectedDroneId || '') === anchor.id ? 'selected' : '',
              ].filter(Boolean).join(' ')}
              style={{
                '--mds-globe-marker-color': anchor.markerColor,
                left: `${anchor.x}px`,
                top: `${anchor.y}px`,
              }}
              onClick={(event) => {
                event.stopPropagation();
                onSelectDrone(anchor.id);
              }}
              onMouseDown={(event) => event.stopPropagation()}
              onPointerDown={(event) => {
                event.preventDefault();
                event.stopPropagation();
                onSelectDrone(anchor.id);
              }}
              onTouchStart={(event) => event.stopPropagation()}
              aria-label={`${anchor.label}${anchor.noMapFix ? ' no GPS fix' : ''}`}
            >
              <span>{anchor.label}</span>
            </button>
          )
        ))}
      </div>
      {selectedDrone && (
        <div
          className={[
            'globe-selected-card-popover',
            selectedScreenPosition?.visible === false ? 'is-offscreen' : '',
            selectedCardPlacement.placeLeft ? 'is-left' : '',
            selectedCardPlacement.placeAbove ? 'is-above' : '',
          ].filter(Boolean).join(' ')}
          style={selectedCardPlacement.style}
          onMouseDown={(event) => event.stopPropagation()}
          onPointerDown={(event) => event.stopPropagation()}
          onTouchStart={(event) => event.stopPropagation()}
        >
          <TacticalDroneCard
            drone={{
              ...selectedDrone,
              position: selectedDrone.position,
              geoPosition: selectedDrone.geoPosition,
            }}
            onClose={() => onSelectDrone(null)}
          />
        </div>
      )}

      {/* Render Compass outside the Canvas */}
      
      <div className="button-container">
        <button
          type="button"
          className="fullscreen-button"
          onClick={toggleFullscreen}
          aria-label="Toggle fullscreen"
        >
          <FaCompressAlt aria-hidden="true" />
        </button>
        <button
          type="button"
          className="focus-button"
          onClick={focusOnDrones}
          aria-label="Focus camera on drones"
        >
          <FaCrosshairs aria-hidden="true" />
        </button>
        <button
          type="button"
          className="toolbox-button"
          onClick={() => setIsToolboxOpen(!isToolboxOpen)}
          aria-label="Toggle 3D view filters"
        >
          <FaSlidersH aria-hidden="true" />
        </button>
      </div>
      {isToolboxOpen && (
        <button
          type="button"
          className="globe-control-backdrop"
          onClick={() => setIsToolboxOpen(false)}
          aria-label="Close 3D view filters"
        />
      )}
      <GlobeControlBox
        drones={drones}
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
        selectedDroneId={selectedDroneId}
        onSelectDrone={onSelectDrone}
        onClose={() => setIsToolboxOpen(false)}
      />
    </div>
  );
}

Globe.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string.isRequired,
    pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    position: PropTypes.arrayOf(PropTypes.number).isRequired,
    state: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    stateLabel: PropTypes.string,
    follow_mode: PropTypes.number,
    altitude: PropTypes.number,
    marker_color: PropTypes.string,
  })).isRequired,
  selectedDroneId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  onSelectDrone: PropTypes.func,
};

Globe.defaultProps = {
  selectedDroneId: null,
  onSelectDrone: () => {},
};
