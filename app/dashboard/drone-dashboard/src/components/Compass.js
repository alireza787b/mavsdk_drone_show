import React, { useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import PropTypes from 'prop-types';
import * as THREE from 'three';
import '../styles/Compass.css';

const Compass = ({ controlsRef }) => {
  const compassRef = useRef();
  const { camera } = useThree();

  useFrame(() => {
    if (compassRef.current && camera) {
      // Calculate azimuthal angle using camera position
      const vector = new THREE.Vector3();
      camera.getWorldDirection(vector);
      const azimuthalAngle = Math.atan2(vector.x, vector.z); // Y-axis is up

      // Convert to degrees
      const azimuthalDeg = THREE.MathUtils.radToDeg(azimuthalAngle);

      // Rotate compass inversely to match north direction
      compassRef.current.style.transform = `rotate(${azimuthalDeg}deg)`;
    }
  });

  return (
    <Html
      style={{ pointerEvents: 'none' }}
      position={[0, 0, 0]}
      transform
      distanceFactor={1}
      // Adjust the following props to position the compass correctly
      style={{
        position: 'absolute',
        top: '20px',
        left: '20px',
        width: '100px',
        height: '100px',
      }}
    >
      <div className="compass-container">
        <svg
          ref={compassRef}
          width="100%"
          height="100%"
          viewBox="0 0 100 100"
          className="compass-rose"
        >
          {/* Outer Circle */}
          <circle cx="50" cy="50" r="48" stroke="#ffffff" strokeWidth="2" fill="rgba(0, 0, 0, 0.5)" />

          {/* Cardinal Points */}
          <text x="50" y="15" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="bold">N</text>
          <text x="85" y="55" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="bold">E</text>
          <text x="50" y="95" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="bold">S</text>
          <text x="15" y="55" textAnchor="middle" fill="#ffffff" fontSize="10" fontWeight="bold">W</text>

          {/* North Arrow */}
          <polygon points="50,25 45,40 55,40" fill="#ff0000" />
          <line x1="50" y1="40" x2="50" y2="80" stroke="#ff0000" strokeWidth="2" />
          <circle cx="50" cy="80" r="3" fill="#ff0000" />
        </svg>
      </div>
    </Html>
  );
};

Compass.propTypes = {
  controlsRef: PropTypes.object.isRequired,
};

export default Compass;
