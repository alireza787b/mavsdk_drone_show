// app/dashboard/drone-dashboard/src/components/Environment.js
import React from 'react';
import { WORLD_SIZE } from '../utilities/utilities';

function Environment({ groundLevel, opacity = 0.5 }) {
  return (
    <mesh position={[0, groundLevel, 0]} rotation={[-Math.PI / 2, 0, 0]}>
      <planeGeometry args={[WORLD_SIZE, WORLD_SIZE]} />
      <meshStandardMaterial
        color="#4CAF50"
        transparent
        opacity={opacity}
      />
    </mesh>
  );
}

export default Environment;
