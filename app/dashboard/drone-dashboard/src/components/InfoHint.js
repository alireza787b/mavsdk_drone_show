import React, { useEffect, useId, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { FaInfoCircle } from 'react-icons/fa';

import '../styles/InfoHint.css';

function InfoHint({ content, label = 'More information', className = '', placement = 'top' }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const tooltipId = useId();

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) {
        setOpen(false);
      }
    };

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        setOpen(false);
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [open]);

  if (!content) {
    return null;
  }

  return (
    <span ref={containerRef} className={`info-hint ${className}`.trim()}>
      <button
        type="button"
        className="info-hint__button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={tooltipId}
        onClick={() => setOpen((current) => !current)}
        title={label}
      >
        <FaInfoCircle />
      </button>
      {open ? (
        <span
          id={tooltipId}
          className={`info-hint__bubble info-hint__bubble--${placement}`}
          role="tooltip"
        >
          {content}
        </span>
      ) : null}
    </span>
  );
}

InfoHint.propTypes = {
  content: PropTypes.node,
  label: PropTypes.string,
  className: PropTypes.string,
  placement: PropTypes.oneOf(['top', 'right', 'bottom', 'left']),
};

export default InfoHint;
