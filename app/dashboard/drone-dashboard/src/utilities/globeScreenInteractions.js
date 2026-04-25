export const DEFAULT_GLOBE_ANCHOR_HIT_RADIUS_PX = 70;

export function getEventClientPoint(event) {
  const touch = event?.touches?.[0] || event?.changedTouches?.[0];
  const source = touch || event;
  const x = Number(source?.clientX);
  const y = Number(source?.clientY);

  if (!Number.isFinite(x) || !Number.isFinite(y)) {
    return null;
  }

  return { x, y };
}

export function findNearestScreenAnchor(
  anchors = [],
  point,
  containerRect = { left: 0, top: 0 },
  maxDistancePx = DEFAULT_GLOBE_ANCHOR_HIT_RADIUS_PX,
) {
  if (!point) {
    return null;
  }

  const localX = point.x - Number(containerRect?.left || 0);
  const localY = point.y - Number(containerRect?.top || 0);
  const maxDistanceSquared = maxDistancePx ** 2;

  return anchors
    .filter((anchor) => anchor?.visible !== false && Number.isFinite(Number(anchor.x)) && Number.isFinite(Number(anchor.y)))
    .map((anchor) => {
      const dx = Number(anchor.x) - localX;
      const dy = Number(anchor.y) - localY;
      return {
        anchor,
        distanceSquared: (dx ** 2) + (dy ** 2),
      };
    })
    .filter((candidate) => candidate.distanceSquared <= maxDistanceSquared)
    .sort((left, right) => left.distanceSquared - right.distanceSquared)[0]?.anchor || null;
}
