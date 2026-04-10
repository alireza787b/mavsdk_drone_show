import React from 'react';
import PropTypes from 'prop-types';

import { getIdentityDoctrineCopy } from '../utilities/missionIdentityUtils';
import '../styles/IdentityDoctrineStrip.css';

const IdentityDoctrineStrip = ({ surface = 'default', className = '' }) => {
  const copy = getIdentityDoctrineCopy(surface);

  return (
    <section className={`identity-doctrine-strip ${className}`.trim()} aria-label="Identity rule">
      <div className="identity-doctrine-strip__copy">
        <span className="identity-doctrine-strip__eyebrow">Identity rule</span>
        <strong>{copy.title}</strong>
      </div>
      <div className="identity-doctrine-strip__chips">
        {copy.chips.map((chip) => (
          <span key={chip.key} className="identity-doctrine-strip__chip">
            <span className="identity-doctrine-strip__chip-label">{chip.label}</span>
            <span className="identity-doctrine-strip__chip-detail">{chip.detail}</span>
          </span>
        ))}
      </div>
    </section>
  );
};

IdentityDoctrineStrip.propTypes = {
  surface: PropTypes.oneOf([
    'default',
    'mission-config',
    'swarm-design',
    'quickscout',
    'swarm-trajectory',
    'fleet-enrollment',
    'launch-map',
  ]),
  className: PropTypes.string,
};

export default IdentityDoctrineStrip;
