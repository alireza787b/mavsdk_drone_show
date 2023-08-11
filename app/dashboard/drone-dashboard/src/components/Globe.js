import React from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { Color, PlaneGeometry } from 'three';
import { useState, useRef, useEffect } from 'react';
import { Html } from '@react-three/drei';
import { MeshLambertMaterial } from 'three';

function Environment() {
  const world_size = 50;
  return (
    <>
      {/* Ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow castShadow>
        <planeGeometry attach="geometry" args={[world_size, world_size]} />
        <meshLambertMaterial 
          attach="material" 
          color="#90EE90"  // Slightly darker green to mimic grass
          side={2}  // Double-sided: FRONT_AND_BACK
        />
      </mesh>

      {/* Grid on the ground */}
      <gridHelper args={[world_size, world_size, '#286328', '#0B340B']} />

      {/* Ambient light */}
      <ambientLight intensity={0.4} />

      {/* Point light to mimic morning sunlight */}
      <pointLight position={[0, 50, 0]} intensity={1} castShadow />
    </>
  );
}





function Drone({ position, hw_ID, state, follow_mode, altitude }) {
  const [isHovered, setIsHovered] = useState(false);
  const [opacity, setOpacity] = useState(0);

  useEffect(() => {
    if (isHovered) {
      setOpacity(1);
    } else {
      const timeout = setTimeout(() => setOpacity(0), 150);  // wait for 300ms before hiding
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
  onPointerOut={(e) => {
    setIsHovered(false);
  }}
>
      <boxGeometry args={[0.5, 0.4, 0.5]} />
      <meshStandardMaterial color={isHovered ? new Color('orange') : new Color('yellow')} />
      <Html>
        <div
          style={{
            background: 'white',
            padding: '5px',
            borderRadius: '5px',
            pointerEvents: 'none',
            whiteSpace: 'nowrap',
            opacity: opacity,  // Adjusted opacity
            transition: 'opacity 0.3s'
          }}
        >
          <ul style={{ listStyleType: 'none', padding: 0, margin: 0 }}>
            <li>HW_ID: {hw_ID}</li>
            <li>State: {state}</li>
            <li>{follow_mode === 0 ? 'LEADER' : `Follows Drone ${follow_mode}`}</li>
            <li>Altitude: {altitude.toFixed(1)}</li>
          </ul>
        </div>
      </Html>
    </mesh>
  );
}





function getOptimalCameraPosition(positions, reference) {
  let maxX = -Infinity, maxZ = -Infinity;
  
  positions.forEach(([x, _, z]) => {
    if (x > maxX) maxX = x;
    if (z > maxZ) maxZ = z;
  });

  // Place the camera above and slightly back from the maximum position
  return [maxX * 1.1, reference[1] + 10, maxZ * 1.1];  // Elevate the camera by 10 units above reference altitude
}


function calculateReferencePoint(drones) {
  let totalLat = 0, totalLon = 0;
  
  drones.forEach(drone => {
    totalLat += drone.position[0];
    totalLon += drone.position[1];
  });

  const droneCount = drones.length;
  return [totalLat / droneCount, totalLon / droneCount, 0];  // Set altitude reference to 0
}


function llaToLocal(lat, lon, alt, reference) {
  const LAT_TO_METERS = 111321;  // Approx. meters per degree latitude at the equator
  const LON_TO_METERS = 111321;  // Approx. meters per degree longitude at the equator

  const north = (lat - reference[0]) * LAT_TO_METERS;  
  const east = (lon - reference[1]) * LON_TO_METERS;
  const up = alt - reference[2];

  // Map to 3D graphics system
  // X is North, Y is Up, Z is East
  return [north, up, east];
}




export default function Globe({ drones }) {
  if (!drones || drones.length === 0) {
    return <div>Loading...</div>; // Display a loading message until at least one drone's data is available
  }

  const referenceDrone = drones[0];
  const referencePoint = [referenceDrone.position[0], referenceDrone.position[1], referenceDrone.position[2]];

  const convertedDrones = drones.map(drone => {
    return {
      hw_ID: drone.hw_ID,
      position: llaToLocal(drone.position[0], drone.position[1], drone.position[2], referencePoint),
      state: drone.state,
      altitude : drone.altitude,
      follow_mode : drone.follow_mode
    };
  });

  // Adjust the initial camera position to be 10 meters higher and southeast of the first drone
  const initialCameraPosition = [
    convertedDrones[0].position[0] - 10,  // South
    convertedDrones[0].position[1] + 10,  // 10 meters Up
    convertedDrones[0].position[2] + 10   // East
  ];

  // console.log("Reference Drone: ", referenceDrone);
  // console.log("Converted Drones data: ", convertedDrones);
  // console.log("Initial Camera Position: ", initialCameraPosition);

  const handleFullScreen = () => {
    const canvas = document.querySelector('canvas');
    if (canvas.requestFullscreen) {
      canvas.requestFullscreen();
    }
  };

  return (
    <div style={{ width: '100%', height: '70vh' }}>
      <Canvas camera={{ position: initialCameraPosition, up: [0, 1, 0] }}>
        <Environment />
        {convertedDrones && convertedDrones.map(drone => (
          <Drone key={drone.hw_ID} position={drone.position} hw_ID={drone.hw_ID} state={drone.state} follow_mode={drone.follow_mode} altitude = {drone.altitude} />
        ))}
        <OrbitControls />
      </Canvas>
      <button onClick={handleFullScreen}>Full Screen</button>
    </div>
  );
}
