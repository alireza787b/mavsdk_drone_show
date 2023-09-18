import React from 'react';
import { useLoader } from '@react-three/fiber';  // Removed TextureLoader from this import
import { RepeatWrapping, TextureLoader } from 'three';  // Added TextureLoader from 'three' instead
import { TEXTURE_REPEAT, WORLD_SIZE} from '../utilities';



const Environment = ({ groundLevel }) => {
  const grassTexture = useLoader(TextureLoader, '/grass1.jpg');
  grassTexture.wrapS = grassTexture.wrapT = RepeatWrapping;
  grassTexture.repeat.set(TEXTURE_REPEAT, TEXTURE_REPEAT);

  return (
    <>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow castShadow>
        <planeGeometry attach="geometry" args={[WORLD_SIZE, WORLD_SIZE]} />
        <meshStandardMaterial map={grassTexture} attach="material" side={2} />
      </mesh>
      <ambientLight intensity={0.6} />
      <hemisphereLight skyColor={'#ffffff'} groundColor={'#000000'} intensity={1} />
    </>
  );
};

export default Environment;
