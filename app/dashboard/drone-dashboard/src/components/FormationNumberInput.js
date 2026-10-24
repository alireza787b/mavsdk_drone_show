import React, { useState } from 'react';
import { formatFormationDistance } from '../utilities/swarmDesignPresentation';

export default function FormationNumberInput({ value, ...props }) {
  const [focused, setFocused] = useState(false);
  return <input {...props} type="number" step="any" value={focused ? value : formatFormationDistance(value)}
    title={String(value ?? '')} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />;
}
