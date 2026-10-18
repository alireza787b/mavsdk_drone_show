import React from 'react';
import SwarmOperations from './SwarmOperations';

// Both entry points use the authoritative saved-cluster preview and start API.
export default function SwarmRuntimeControls() {
  return <SwarmOperations showMap />;
}
