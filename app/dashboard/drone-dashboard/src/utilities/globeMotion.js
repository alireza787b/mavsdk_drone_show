const DEFAULT_SMOOTHING_RATE = 8;
const DEFAULT_MAX_DISPLAY_SPEED_MPS = 35;

function finiteVector(position = []) {
  return [0, 1, 2].map((index) => {
    const value = Number(position[index]);
    return Number.isFinite(value) ? value : 0;
  });
}

/**
 * Move a display position toward the latest telemetry target without allowing
 * a large GPS/network jump to become a visible rocket motion. This is strictly
 * a presentation helper; it never changes the command or guidance position.
 */
export function interpolateGlobePosition(current, target, deltaSeconds, options = {}) {
  const currentVector = finiteVector(current);
  const targetVector = finiteVector(target);
  const delta = Math.max(0, Math.min(Number(deltaSeconds) || 0, 0.25));
  const smoothingRate = Number(options.smoothingRate) > 0
    ? Number(options.smoothingRate)
    : DEFAULT_SMOOTHING_RATE;
  const maxSpeed = Number(options.maxDisplaySpeedMps) > 0
    ? Number(options.maxDisplaySpeedMps)
    : DEFAULT_MAX_DISPLAY_SPEED_MPS;
  const alpha = 1 - Math.exp(-smoothingRate * delta);
  const proposed = currentVector.map((value, index) => value + ((targetVector[index] - value) * alpha));
  const distance = Math.sqrt(proposed.reduce((sum, value, index) => sum + ((value - currentVector[index]) ** 2), 0));
  const maxStep = maxSpeed * delta;

  if (distance <= maxStep || distance === 0) {
    return proposed;
  }

  const scale = maxStep / distance;
  return currentVector.map((value, index) => value + ((proposed[index] - value) * scale));
}

export const GLOBE_MOTION_DEFAULTS = Object.freeze({
  smoothingRate: DEFAULT_SMOOTHING_RATE,
  maxDisplaySpeedMps: DEFAULT_MAX_DISPLAY_SPEED_MPS,
});

