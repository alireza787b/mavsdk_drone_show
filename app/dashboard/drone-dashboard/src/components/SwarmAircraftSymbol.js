import React from 'react';

/** Screen-sized multirotor symbol: a schematic, never a physical footprint. */
export function AircraftSilhouette({ ghost = false, nose = false }) {
  return <g className={`aircraft-silhouette ${ghost ? 'is-ghost' : ''}`} aria-hidden="true">
    <path d="M -10 -10 L 10 10 M 10 -10 L -10 10" className="aircraft-silhouette__arms" />
    {[[-10, -10], [10, -10], [-10, 10], [10, 10]].map(([x, y]) => <circle key={`${x}:${y}`} cx={x} cy={y} r="6" />)}
    <path d="M 0 -9 L 5 2 L 3 8 L -3 8 L -5 2 Z" />
    {nose && <path d="M -3 -20 L 0 -25 L 3 -20" className="aircraft-silhouette__nose" />}
  </g>;
}

export function HeightChoiceSymbol({ mode }) {
  const offset = mode === 'level' ? 0 : 8;
  return <svg viewBox="0 0 64 34" aria-hidden="true" focusable="false">
    <path d={mode === 'keep' ? 'M 5 29 H 59 M 5 23 H 59' : 'M 5 29 H 59'} className="capture-height-symbol__guide" />
    {[{ x: 18, y: 10 }, { x: 46, y: 10 + offset }].map(p => <g key={p.x} transform={`translate(${p.x} ${p.y})`}>
      <path d="M -9 0 H 9 M -4 0 L -6 -4 M 4 0 L 6 -4" />
      <ellipse cx="-8" cy="-4" rx="5" ry="1.5" /><ellipse cx="8" cy="-4" rx="5" ry="1.5" />
    </g>)}
    {mode === 'current' && <path d="M 32 5 V 22 M 29 8 L 32 5 L 35 8 M 29 19 L 32 22 L 35 19" />}
  </svg>;
}
