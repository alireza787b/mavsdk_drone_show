// src/config/routeDocs.js
// Route-to-documentation metadata used by operator help links and UI audit checks.

export const DEFAULT_DOC_BRANCH = 'main-candidate';

export const ROUTE_DOCS = Object.freeze([
  {
    path: '/',
    label: 'Dashboard guide',
    docPath: 'docs/guides/dashboard-operator.md',
    feature: 'dashboard',
  },
  {
    path: '/mission-control',
    label: 'Dashboard guide',
    docPath: 'docs/guides/dashboard-operator.md',
    feature: 'dashboard',
  },
  {
    path: '/mission-config',
    label: 'Mission config guide',
    docPath: 'docs/guides/config-json-format.md',
    feature: 'mission-config',
  },
  {
    path: '/fleet-enrollment',
    label: 'Enrollment guide',
    docPath: 'docs/guides/mds-init-setup.md',
    feature: 'fleet-enrollment',
  },
  {
    path: '/fleet-ops',
    label: 'Fleet ops guide',
    docPath: 'docs/guides/fleet-ops.md',
    feature: 'fleet-ops',
  },
  {
    path: '/px4-parameters',
    label: 'PX4 parameters guide',
    docPath: 'docs/px4-parameters.md',
    feature: 'px4-parameters',
  },
  {
    path: '/globe-view',
    label: 'Map setup guide',
    docPath: 'docs/guides/mapbox-setup.md',
    feature: 'globe-view',
  },
  {
    path: '/runtime-admin',
    label: 'Runtime config guide',
    docPath: 'docs/guides/runtime-config-sources.md',
    feature: 'runtime-admin',
  },
  {
    path: '/sitl-control',
    label: 'SITL control guide',
    docPath: 'docs/guides/sitl-control.md',
    feature: 'sitl-control',
  },
  {
    path: '/logs',
    label: 'Logging guide',
    docPath: 'docs/guides/logging-system.md',
    feature: 'logs',
  },
  {
    path: '/drone-show-design',
    label: 'Drone show guide',
    docPath: 'docs/features/drone-show.md',
    feature: 'drone-show',
  },
  {
    path: '/manage-drone-show',
    label: 'Drone show guide',
    docPath: 'docs/features/drone-show.md',
    feature: 'drone-show',
  },
  {
    path: '/custom-show',
    label: 'Custom show guide',
    docPath: 'docs/features/drone-show.md',
    feature: 'custom-show',
  },
  {
    path: '/swarm-design',
    label: 'Smart swarm guide',
    docPath: 'docs/features/smart-swarm.md',
    feature: 'swarm-design',
  },
  {
    path: '/trajectory-planning',
    label: 'Trajectory guide',
    docPath: 'docs/features/swarm-trajectory.md',
    feature: 'trajectory-planning',
  },
  {
    path: '/swarm-trajectory',
    label: 'Swarm trajectory guide',
    docPath: 'docs/features/swarm-trajectory.md',
    feature: 'swarm-trajectory',
  },
  {
    path: '/quickscout',
    label: 'QuickScout guide',
    docPath: 'docs/quickscout.md',
    feature: 'quickscout',
  },
  {
    path: '/drone-detail',
    label: 'Drone detail guide',
    docPath: 'docs/guides/dashboard-operator.md',
    feature: 'drone-detail',
  },
]);

const normalizeRoutePath = (pathname = '/') => {
  const trimmed = String(pathname || '/').trim();
  if (!trimmed || trimmed === '/') {
    return '/';
  }
  const withoutQuery = trimmed.split(/[?#]/)[0] || '/';
  const withLeadingSlash = withoutQuery.startsWith('/') ? withoutQuery : `/${withoutQuery}`;
  return withLeadingSlash.length > 1 ? withLeadingSlash.replace(/\/+$/, '') : withLeadingSlash;
};

export const ROUTE_DOCS_BY_PATH = Object.freeze(
  ROUTE_DOCS.reduce((accumulator, entry) => {
    accumulator[normalizeRoutePath(entry.path)] = Object.freeze({ ...entry });
    return accumulator;
  }, {})
);

export function getRouteDoc(pathname = '/') {
  return ROUTE_DOCS_BY_PATH[normalizeRoutePath(pathname)] || null;
}

export function normalizeGithubRepoUrl(repoUrl = '') {
  const value = String(repoUrl || '').trim().replace(/\.git$/, '').replace(/\/$/, '');
  if (!value) {
    return '';
  }

  const ownerRepoMatch = value.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/);
  if (ownerRepoMatch) {
    return `https://github.com/${ownerRepoMatch[1]}/${ownerRepoMatch[2]}`;
  }

  const sshMatch = value.match(/^git@github\.com:([^/]+)\/(.+)$/);
  if (sshMatch) {
    return `https://github.com/${sshMatch[1]}/${sshMatch[2]}`;
  }

  const httpsMatch = value.match(/^https:\/\/github\.com\/([^/]+)\/(.+)$/);
  if (httpsMatch) {
    return `https://github.com/${httpsMatch[1]}/${httpsMatch[2]}`;
  }

  return value;
}

export function buildDocsUrl(doc, { repoUrl = '', repoWebUrl = '', branch = DEFAULT_DOC_BRANCH } = {}) {
  if (!doc?.docPath) {
    return '';
  }

  if (/^https?:\/\//i.test(doc.docPath)) {
    return doc.docPath;
  }

  const repoBase = normalizeGithubRepoUrl(repoWebUrl || repoUrl);
  if (!repoBase) {
    return doc.docPath;
  }

  const safeBranch = branch || DEFAULT_DOC_BRANCH;
  return `${repoBase}/blob/${safeBranch}/${doc.docPath}`;
}

export function getRouteDocUrl(pathname = '/', options = {}) {
  const doc = getRouteDoc(pathname);
  return buildDocsUrl(doc, options);
}
