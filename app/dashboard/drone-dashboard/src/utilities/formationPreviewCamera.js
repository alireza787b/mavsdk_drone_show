import { worldToView } from './swarmFormationGeometry';

export const INITIAL_PREVIEW_CAMERA = { azimuth: -.6, elevation: .6, x: 0, y: 0, scale: 35 };
export const previewZoom = scale => Math.max(.01, Math.min(1000, scale));

/** Orthographic 3D, in metres. Presentation only; never inverse-edits geometry. */
export function projectPreviewPoint(position, view, camera, frame = 'ned', heading = 0) {
  const p = worldToView(position, frame, heading);
  if (view === 'top') return { x: p.axis2, y: p.axis1, depth: p.up };
  if (view === 'front') return { x: p.axis2, y: p.up, depth: p.axis1 };
  if (view === 'side') return { x: p.axis1, y: p.up, depth: p.axis2 };
  const c = Math.cos(camera.azimuth), s = Math.sin(camera.azimuth);
  const forward = p.axis2 * s + p.axis1 * c;
  return { x: p.axis2 * c - p.axis1 * s,
    y: p.up * Math.cos(camera.elevation) - forward * Math.sin(camera.elevation),
    depth: forward * Math.cos(camera.elevation) + p.up * Math.sin(camera.elevation) };
}

export function fitPreviewCamera(points, size, camera) {
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  const lowX = Math.min(-1, ...xs), highX = Math.max(1, ...xs);
  const lowY = Math.min(-1, ...ys), highY = Math.max(1, ...ys);
  return { ...camera, x: (lowX + highX) / 2, y: (lowY + highY) / 2,
    scale: previewZoom(Math.min(Math.max(60, size.width - 150) / (highX - lowX),
      Math.max(60, size.height - 130) / (highY - lowY))) };
}
