import React, { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import '../styles/Compass.css';

const Compass = ({ controlsRef }) => {
  const compassRef = useRef();

  useFrame(() => {
    if (compassRef.current && controlsRef.current) {
      const azimuthalAngle = controlsRef.current.getAzimuthalAngle();
      // Rotate the compass to always point north
      compassRef.current.style.transform = `rotate(${azimuthalAngle}rad)`;
    }
  });

  return (
    <Html fullscreen style={{ pointerEvents: 'none' }}>
      <div className="compass-container">
        <div ref={compassRef} className="compass-arrow">▲</div>
      </div>
    </Html>
  );
};

export default Compass;
