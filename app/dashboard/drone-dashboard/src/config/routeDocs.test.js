import {
  buildDocsUrl,
  getRouteDoc,
  getRouteDocUrl,
  normalizeGithubRepoUrl,
  ROUTE_DOCS,
} from './routeDocs';

describe('routeDocs', () => {
  test('declares route documentation metadata for top-level operator routes', () => {
    expect(ROUTE_DOCS.length).toBeGreaterThan(10);
    expect(getRouteDoc('/fleet-ops')).toMatchObject({
      label: 'Fleet ops guide',
      docPath: 'docs/guides/fleet-ops.md',
    });
    expect(getRouteDoc('/mission-control')).toMatchObject({
      feature: 'dashboard',
      docPath: 'docs/guides/dashboard-operator.md',
    });
  });

  test('normalizes route paths before lookup', () => {
    expect(getRouteDoc('fleet-ops/')).toEqual(getRouteDoc('/fleet-ops'));
    expect(getRouteDoc('/fleet-ops?tab=access')).toEqual(getRouteDoc('/fleet-ops'));
    expect(getRouteDoc('/missing-route')).toBeNull();
  });

  test('normalizes GitHub repo references for docs links', () => {
    expect(normalizeGithubRepoUrl('demo/customer-mds')).toBe('https://github.com/demo/customer-mds');
    expect(normalizeGithubRepoUrl('git@github.com:demo/customer-mds.git')).toBe('https://github.com/demo/customer-mds');
    expect(normalizeGithubRepoUrl('https://github.com/demo/customer-mds.git')).toBe('https://github.com/demo/customer-mds');
  });

  test('builds branch-aware GitHub docs URLs when repo metadata is available', () => {
    const doc = getRouteDoc('/runtime-admin');

    expect(buildDocsUrl(doc, {
      repoUrl: 'git@github.com:demo/customer-mds.git',
      branch: 'release/test',
    })).toBe('https://github.com/demo/customer-mds/blob/release/test/docs/guides/runtime-config-sources.md');

    expect(getRouteDocUrl('/quickscout', {
      repoWebUrl: 'https://github.com/demo/customer-mds',
    })).toBe('https://github.com/demo/customer-mds/blob/main/docs/quickscout.md');
  });

  test('falls back to repo-relative paths without repo metadata', () => {
    expect(buildDocsUrl(getRouteDoc('/globe-view'))).toBe('docs/guides/mapbox-setup.md');
  });
});
