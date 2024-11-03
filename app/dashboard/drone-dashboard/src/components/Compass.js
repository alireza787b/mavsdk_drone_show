// src/components/Compass.js

import React, { useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import '../styles/Compass.css';
import { Vector3 } from 'three';
import EnhancedCompass from '../assets/EnhancedCompass.svg'; // Ensure the path is correct

const Compass = () => {
  const compassRef = useRef();
  const { camera } = useThree();

  useFrame(() => {
    if (compassRef.current) {
      // Define the world's north direction (positive X-axis)
      const worldNorth = new Vector3(1, 0, 0);
      
      // Get the camera's direction vector
      const cameraDirection = new Vector3();
      camera.getWorldDirection(cameraDirection);

      // Project the camera direction onto the XZ plane
      cameraDirection.y = 0;
      cameraDirection.normalize();

      // Calculate the angle between the world's north and the camera's direction
      const angle = Math.atan2(cameraDirection.z, cameraDirection.x);

      // Convert the angle from radians to degrees and rotate the compass accordingly
      const angleDeg = (angle * 180) / Math.PI;
      compassRef.current.style.transform = `rotate(${ -angleDeg }deg)`;
    }
  });

  return (
    <Html
      style={{ pointerEvents: 'none' }} // Ensure the compass doesn't intercept any mouse events
    >
      <div className="enhanced-compass-container">
        <img
          ref={compassRef}
          src={EnhancedCompass}
          alt="Compass"
          className="enhanced-compass-image"
        />
      </div>
    </Html>
  );
};

export default Compass;
