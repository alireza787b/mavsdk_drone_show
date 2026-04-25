import React from 'react';
import { useLocation } from 'react-router-dom';

import { GIT_BRANCH, GIT_REPO } from '../version';
import { DocsLink } from './ui';

function buildRepoWebUrl(repo = '') {
  const normalized = String(repo || '').trim().replace(/^https?:\/\/github\.com\//, '').replace(/\.git$/, '');
  return normalized ? `https://github.com/${normalized}` : '';
}

export default function RouteDocsShortcut() {
  const location = useLocation();

  return (
    <div className="route-docs-shortcut" aria-label="Current page documentation">
      <DocsLink
        route={location.pathname}
        repoWebUrl={buildRepoWebUrl(GIT_REPO)}
        branch={GIT_BRANCH}
        compact
      />
    </div>
  );
}
