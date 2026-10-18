import React from 'react';
import { FaNetworkWired } from 'react-icons/fa';
import MissionCard from './MissionCard';
import SwarmOperations from './SwarmOperations';

export default function DashboardSmartSwarmStart({ review = false, onReview, onBack }) {
  if (!review) return <MissionCard icon={<FaNetworkWired aria-hidden="true" />} category="Live formation"
    label="Smart Swarm" summary="Takeoff · Follow · Return" onClick={onReview} />;
  return <div>
    <SwarmOperations />
    <button className="operator-button operator-button--ghost" type="button" onClick={onBack}>Back</button>
  </div>;
}
