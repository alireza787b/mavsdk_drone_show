import { fitPreviewCamera, INITIAL_PREVIEW_CAMERA, previewZoom, projectPreviewPoint } from './formationPreviewCamera';
test('all projections preserve the common height datum and correctly rotate Body axes', () => {
  const p={north:6,east:2,up:3},c=INITIAL_PREVIEW_CAMERA;
  expect(projectPreviewPoint(p,'top',c)).toMatchObject({x:2,y:6});
  expect(projectPreviewPoint(p,'front',c)).toMatchObject({x:2,y:3});
  expect(projectPreviewPoint(p,'side',c)).toMatchObject({x:6,y:3});
  expect(projectPreviewPoint(p,'top',c,'body',90).x).toBeCloseTo(-6);
  const a=projectPreviewPoint(p,'3d',c),b=projectPreviewPoint(p,'3d',{...c,azimuth:c.azimuth+1});
  expect(a.x).not.toBeCloseTo(b.x);
  expect(p).toEqual({north:6,east:2,up:3});
});
test.each([1,50,1000])('fit includes the whole formation without changing geometry: span%s', span=>{
  const points=[{x:-span,y:-span},{x:span,y:span}];
  const fit=fitPreviewCamera(points,{width:390,height:300},INITIAL_PREVIEW_CAMERA);
  points.forEach(p=>{expect(Math.abs(p.x-fit.x)*fit.scale).toBeLessThan(195);expect(Math.abs(p.y-fit.y)*fit.scale).toBeLessThan(150);});
  expect(Number.isFinite(fit.scale)).toBe(true);
  expect(previewZoom(Infinity)).toBe(1000);
  expect(previewZoom(0)).toBe(.01);
});
