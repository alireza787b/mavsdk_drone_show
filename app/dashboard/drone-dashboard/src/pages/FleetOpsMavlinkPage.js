import React from 'react';
import FleetOpsSidecarPage, { MAVLINK_SIDECAR_CONFIG } from './FleetOpsSidecarPage';

export default function FleetOpsMavlinkPage() {
  return <FleetOpsSidecarPage config={MAVLINK_SIDECAR_CONFIG} />;
}
