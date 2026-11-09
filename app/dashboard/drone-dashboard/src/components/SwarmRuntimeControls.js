import React from 'react';
import SwarmOperations from './SwarmOperations';

// The dedicated workspace owns the authoritative saved-cluster control flow.
export default function SwarmRuntimeControls() {
  return <SwarmOperations />;
}
