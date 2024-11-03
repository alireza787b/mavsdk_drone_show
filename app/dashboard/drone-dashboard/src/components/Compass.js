import React, { useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import compassRose from '../assets/compass-rose.png'; // Ensure you have this image
import '../styles/Compass.css';

const Compass = () => {
  const compassRef = useRef();
  const { camera } = useThree();

  useFrame(() => {
    if (compassRef.current) {
      // Get the camera's rotation around the Y-axis (yaw)
      const yaw = camera.rotation.y;

      // Rotate the compass in the opposite direction to simulate a real compass
      compassRef.current.style.transform = `rotate(${-yaw}rad)`;
    }
  });

  return (
    <Html
      fullscreen // This ensures the HTML element covers the entire screen
      style={{ pointerEvents: 'none' }} // So it doesn't interfere with mouse events
    >
      <div className="compass-container">
        <img ref={compassRef} src={compassRose} alt="Compass" className="compass-image" />
      </div>
    </Html>
  );
};

export default Compass;
