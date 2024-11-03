import React, { useRef } from 'react';
import { useFrame, useThree } from '@react-three/fiber';
import { Html } from '@react-three/drei';
import * as THREE from 'three';
import compassSVG from '../assets/compass-rose.png';
import '../styles/Compass.css';

const Compass = () => {
  const compassRef = useRef();
  const { camera } = useThree();

  useFrame(() => {
    if (compassRef.current) {
      // Get the camera's direction vector
      const direction = new THREE.Vector3();
      camera.getWorldDirection(direction);

      // Calculate the angle between the camera's direction and the north direction (0, 0, 1)
      const north = new THREE.Vector3(0, 0, 1);
      const angle = north.angleTo(new THREE.Vector3(direction.x, 0, direction.z));

      // Determine the sign of the angle using the cross product
      const cross = north.clone().cross(new THREE.Vector3(direction.x, 0, direction.z));
      const sign = cross.y < 0 ? -1 : 1;
      const degrees = sign * THREE.MathUtils.radToDeg(angle);

      // Apply rotation to the compass
      compassRef.current.style.transform = `rotate(${degrees}deg)`;
    }
  });

  return (
    <Html
      style={{ pointerEvents: 'none' }}
      className="compass-container"
    >
      <div className="compass">
        <img ref={compassRef} src={compassSVG} alt="Compass" className="compass-image" />
      </div>
    </Html>
  );
};

export default Compass;
