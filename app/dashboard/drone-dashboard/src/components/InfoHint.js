import React, { useEffect, useId, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { FaInfoCircle } from 'react-icons/fa';

import '../styles/InfoHint.css';

function InfoHint({ content, label = 'More information', className = '', placement = 'top', icon = <FaInfoCircle />, hoverable = false }) {
  const [openedBy, setOpenedBy] = useState(null);
  const containerRef = useRef(null);
  const tooltipId = useId();
  const open = Boolean(openedBy);

  useEffect(() => {
    if (!open) {
      return undefined;
    }

    const handlePointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) {
        setOpenedBy(null);
      }
    };

    const handleEscape = (event) => {
      if (event.key === 'Escape') {
        setOpenedBy(null);
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
    <span ref={containerRef} className={`info-hint ${className}`.trim()}
      onMouseEnter={hoverable ? () => setOpenedBy(current => current || 'hover') : undefined}
      onMouseLeave={hoverable ? () => setOpenedBy(current => current === 'hover' ? null : current) : undefined}>
      <button
        type="button"
        className="info-hint__button"
        aria-label={label}
        aria-expanded={open}
        aria-controls={tooltipId}
        aria-describedby={open ? tooltipId : undefined}
        onClick={() => setOpenedBy(current => current === 'click' ? null : 'click')}
        onFocus={hoverable ? () => setOpenedBy(current => current === 'click' ? current : 'focus') : undefined}
        onBlur={hoverable ? () => setOpenedBy(null) : undefined}
        onKeyDown={event => {
          if (open && event.key === 'Escape') {
            event.stopPropagation();
            setOpenedBy(null);
          }
        }}
        title={hoverable ? undefined : label}
      >
        {icon}
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
  icon: PropTypes.node,
  hoverable: PropTypes.bool,
};

export default InfoHint;
