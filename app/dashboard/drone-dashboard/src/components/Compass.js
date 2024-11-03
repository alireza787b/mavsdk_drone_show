import React, { useRef, useEffect } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import compassRose from '../assets/compass-rose.png'; // You need to have a compass rose image in your assets
import '../styles/Compass.css';

const Compass = () => {
  const compassRef = useRef();
  const { camera } = useThree();

  useFrame(() => {
    if (compassRef.current) {
      // Get the camera's rotation around the Y-axis (yaw)
      const yaw = camera.rotation.y;

      // Rotate the compass in the opposite direction to simulate a real compass
      compassRef.current.style.transform = `rotate(${yaw}rad)`;
    }
  });

  return (
    <div className="compass-container">
      <img ref={compassRef} src={compassRose} alt="Compass" className="compass-image" />
    </div>
  );
};

export default Compass;
