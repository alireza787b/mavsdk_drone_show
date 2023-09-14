import React, { useState, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import { Color, RepeatWrapping, TextureLoader } from 'three';
import { useLoader } from '@react-three/fiber';

import GlobeControlBox from './GlobeControlBox';


// Constants for conversions and world setup
const LAT_TO_METERS = 111321;
const LON_TO_METERS = 111321;
const WORLD_SIZE = 400;
const TEXTURE_REPEAT = 10;

// Fetch the elevation based on latitude and longitude
const getElevation = async (lat, lon) => {
  try {
    const url = `http://localhost:5001/elevation?lat=${lat}&lon=${lon}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
    const data = await response.json();
    return data.results[0]?.elevation || null;
  } catch (error) {
    console.error(`Failed to fetch elevation data: ${error}`);
    return null;
  }
};

// Timeout Promise for fetch operations
const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));

// Convert Latitude, Longitude, Altitude to local coordinates
const llaToLocal = (lat, lon, alt, reference) => {
  const north = (lat - reference[0]) * LAT_TO_METERS;
  const east = (lon - reference[1]) * LON_TO_METERS;
  const up = alt - reference[2];
  return [north, up, east];
};

// Environment setup component
const Environment = ({ groundLevel  }) => {
  const grassTexture = useLoader(TextureLoader, '/grass1.jpg');
  grassTexture.wrapS = grassTexture.wrapT = RepeatWrapping;
  grassTexture.repeat.set(TEXTURE_REPEAT, TEXTURE_REPEAT);

  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0,0, 0]} receiveShadow castShadow>
        <planeGeometry attach="geometry" args={[WORLD_SIZE, WORLD_SIZE]} />
        <meshStandardMaterial map={grassTexture} attach="material" side={2} />
      </mesh>
      <ambientLight intensity={0.6} />
      <hemisphereLight skyColor={'#ffffff'} groundColor={'#000000'} intensity={1} />
    </>
  );
};


// Tooltip for drones
const DroneTooltip = ({ hw_ID, state, follow_mode, altitude, opacity }) => (
  <div style={{
    background: 'rgba(255, 255, 255, 0.8)',
    padding: '5px',
    borderRadius: '5px',
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
    opacity: opacity,
    transition: 'opacity 0.3s',
    boxShadow: '2px 2px 8px rgba(0,0,0,0.2)',
    fontWeight: '500'
  }}>
    <ul style={{ listStyleType: 'none', padding: 0, margin: 0 }}>
      <li>HW_ID: {hw_ID}</li>
      <li>State: {state}</li>
      <li>{follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}</li>
      <li>Altitude: {altitude.toFixed(1)}</li>
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
      <sphereGeometry args={[1]} />
      <meshStandardMaterial 
        color={isHovered ? new Color('orange') : new Color('#1E4D8C')}
        emissive={isHovered ? new Color('orange') : new Color('#1E4D8C')}
        emissiveIntensity={0.5}
        metalness={0.6}
        roughness={0.4}
      />
      <Html>
        <DroneTooltip hw_ID={hw_ID} state={state} follow_mode={follow_mode} altitude={altitude} opacity={opacity} />
      </Html>
    </mesh>
  );
};

// Main Globe component
export default function Globe({ drones }) {
  const [referencePoint, setReferencePoint] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [showGround, setShowGround] = useState(true);
  const [groundLevel, setGroundLevel] = useState(0);
  const [droneVisibility, setDroneVisibility] = useState({});
  const [isToolboxOpen, setIsToolboxOpen] = useState(false);
  const [showGrid, setShowGrid] = useState(true);


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
  
  

// Function to handle 'Get Terrain' button click
const handleGetTerrainClick = () => {
  if (referencePoint) {
    fetchAndUpdateTerrain(referencePoint[0], referencePoint[1], setGroundLevel);
  }
};

// Fetch terrain elevation and update ground level
const fetchAndUpdateTerrain = async (lat, lon, setGroundLevel) => {
  const elevation = await Promise.race([getElevation(lat, lon), timeoutPromise(5000)]);
  if (elevation !== null) {
    setGroundLevel(elevation);
  }
};

  useEffect(() => {
    if (referencePoint) {
      setReferencePoint([referencePoint[0], referencePoint[1], groundLevel]);
    }
  }, [groundLevel]);
  

  useEffect(() => {
    const setInitialReferencePoint = async () => {
      if (drones?.length) {
        setIsLoading(true);
  
        // Existing logic for setting initial reference point
        if (!referencePoint) {
          const avgLat = drones.reduce((sum, drone) => sum + drone.position[0], 0) / drones.length;
          const avgLon = drones.reduce((sum, drone) => sum + drone.position[1], 0) / drones.length;
          const avgAlt = drones.reduce((sum, drone) => sum + drone.position[2], 0) / drones.length;
  
          const elevation = await Promise.race([getElevation(avgLat, avgLon), timeoutPromise(5000)]);
          const localReference = [avgLat, avgLon, elevation ?? avgAlt];
          setReferencePoint(localReference);
          
          // Update groundLevel only if it hasn't been set yet
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
  
  
  

  if (isLoading || !drones?.length || !referencePoint) return <div>Loading...</div>;

  const convertedDrones = drones.map(drone => ({
    ...drone,
    position: llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint),
  }));
  
  const initialCameraPosition = [10, 10, 10];
  
  const toggleDroneVisibility = (droneId) => {
    setDroneVisibility(prevState => ({
      ...prevState,
      [droneId]: !prevState[droneId]
    }));
  };
  
  
  

  return (

<div id="scene-container" style={{ width: '100%', height: '70vh', position: 'relative' }}>


    <div style={{ width: '100%', height: '70vh', position: 'relative' }}> {/* Set to relative */}
      <Canvas camera={{ position: initialCameraPosition, up: [0, 1, 0] }}>
        {showGround && <Environment groundLevel={groundLevel} />}
        {convertedDrones.map(drone => (
          droneVisibility[drone.hw_ID] && <Drone key={drone.hw_ID} {...drone} />
        ))}
        {showGrid && <gridHelper args={[WORLD_SIZE, 50]} />}  
        <OrbitControls />
      </Canvas>
      <div 
  onClick={() => setIsToolboxOpen(!isToolboxOpen)} 
  style={{
    position: 'absolute', 
    top: '10px', 
    right: '10px', 
    zIndex: 1000, 
    cursor: 'pointer', // Makes the cursor a pointer
    transition: 'transform 0.2s ease' // Adds a transition
  }}
  onMouseOver={(e) => e.currentTarget.style.transform = 'scale(1.3)'} // Scales up on hover
  onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'} // Scales back to original size
>
  🛠️ {/* You can replace this with an actual icon */}
</div>
<div 
  onClick={toggleFullscreen}
  style={{
    position: 'absolute', 
    top: '10px', 
    left: '10px', 
    zIndex: 1000, 
    cursor: 'pointer', 
    transition: 'transform 0.2s ease'
  }}
  onMouseOver={(e) => {
    e.currentTarget.style.transform = 'scale(1.3)';
    e.currentTarget.title = 'Toggle Fullscreen';
  }}
  onMouseOut={(e) => e.currentTarget.style.transform = 'scale(1)'}
>
  ⛶  {/* Fullscreen icon */}
</div>


      {isToolboxOpen && <GlobeControlBox
        setShowGround={setShowGround}
        showGround={showGround}
        setGroundLevel={setGroundLevel}
        groundLevel={groundLevel}
        toggleDroneVisibility={toggleDroneVisibility}
        droneVisibility={droneVisibility}
        isToolboxOpen={isToolboxOpen}  // Pass it as a prop
        showGrid={showGrid}
  setShowGrid={setShowGrid}
  handleGetTerrainClick={handleGetTerrainClick}  // Pass the function as a prop


      />}
    </div>
    </div>
  );
  
}
