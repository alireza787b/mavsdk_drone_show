import React, { useState, useEffect } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Html } from '@react-three/drei';
import { Color, RepeatWrapping, TextureLoader } from 'three';
import { useLoader } from '@react-three/fiber';
import { getElevation, llaToLocal } from '../utilities';
import Environment from './Environment';
import GlobeControlBox from './GlobeControlBox';
import { TEXTURE_REPEAT, WORLD_SIZE} from '../utilities';
import useElevation from '../useElevation';  // Update the path if necessary
import '../styles/Globe.css'; // Import the CSS


// Constants for conversions and world setup



// Timeout Promise for fetch operations
const timeoutPromise = (ms) => new Promise((resolve) => setTimeout(() => resolve(null), ms));






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

const MemoizedDrone = React.memo(Drone);


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
          setIsLoading(true);
      
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
  return (
    <div className="loading-container">
      <div className="loading-message">
        Waiting for drone to connect...
      </div>
    </div>
  );

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
      <Canvas camera={{ position: initialCameraPosition, up: [0, 1, 0] }}>
        {showGround && <Environment groundLevel={groundLevel} />}
        {/* {convertedDrones.map(drone => (
          droneVisibility[drone.hw_ID] && <Drone key={drone.hw_ID} {...drone} />
        ))} */}
    {/*  Using memorize to see how it works. */}
{convertedDrones.map(drone => (
  droneVisibility[drone.hw_ID] && <MemoizedDrone key={drone.hw_ID} {...drone} />
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
  );
  
}
