import React from 'react';
import { Link } from 'react-router-dom';
import { FaArrowLeft } from 'react-icons/fa';
import '../styles/MaintenancePage.css';
import FleetOpsSidecarPage, { MAVLINK_SIDECAR_CONFIG } from './FleetOpsSidecarPage';

export default function FleetOpsMavlinkPage() {
  return <>
    <Link to="/maintenance" className="maintenance-back"><FaArrowLeft aria-hidden="true" /> Maintenance</Link>
    <FleetOpsSidecarPage config={MAVLINK_SIDECAR_CONFIG} />
  </>;
}
