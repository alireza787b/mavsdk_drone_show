import React from 'react';
import { FaBolt } from 'react-icons/fa';

/** Measured radio strength only, not packet loss or Internet/VPN quality. */
export function WifiStrength({ percent }) {
  const known = Number.isFinite(percent) && percent >= 0 && percent <= 100;
  const level = known ? Math.ceil(percent * 3 / 100) : null;
  return <svg viewBox="0 0 28 24" className="fleet-wifi-gauge" data-level={level ?? 'unknown'} aria-hidden="true">
    {['M3 8a17 17 0 0 1 22 0', 'M6.5 12a11.5 11.5 0 0 1 15 0', 'M10 16a6 6 0 0 1 8 0'].map((d, index) =>
      <path key={d} d={d} data-active={known && level >= 3 - index} />)}
    {known ? <circle cx="14" cy="20" r="1.6" /> : <text x="14" y="23" textAnchor="middle">?</text>}
  </svg>;
}

/** State of charge is supplied by PX4; voltage never manufactures a fill. */
export function BatteryGauge({ battery }) {
  const known = Number.isFinite(battery.remaining) && battery.remaining >= 0 && battery.remaining <= 100;
  const charging = battery.current && battery.chargeState === 7 && !battery.faultBitmask && battery.tone !== 'danger';
  return <span className="fleet-battery-instrument" data-current={battery.current}>
    <svg viewBox="0 0 46 22" className="fleet-battery-gauge" data-charge={known ? Math.round(battery.remaining) : 'unknown'} aria-hidden="true">
      <rect className="fleet-battery-gauge__outline" x="1" y="1" width="40" height="20" rx="2" />
      <path d="M44 8v6" className="fleet-battery-gauge__terminal" />
      {known && <rect className="fleet-battery-gauge__fill" x="3.5" y="3.5" width={35 * battery.remaining / 100} height="15" />}
      <text x="21" y="15" textAnchor="middle">{known ? `${Math.round(battery.remaining)}%` : '—'}</text>
    </svg>
    {charging && <FaBolt className="fleet-battery-instrument__charging" aria-hidden="true" />}
  </span>;
}
