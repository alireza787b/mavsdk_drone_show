import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SidebarMenu from './SidebarMenu';

jest.mock('../hooks/useTheme', () => ({
  useTheme: jest.fn(() => ({ isDark: false })),
}));

jest.mock('./ThemeToggle', () => jest.fn(() => <div>Theme toggle</div>));
jest.mock('./CurrentTime', () => jest.fn(() => <span>12:00</span>));
jest.mock('./GitInfo', () => jest.fn(() => <div>Git info</div>));
jest.mock('../hooks/useGcsGitInfo', () => jest.fn(() => ({
  repo: 'demo/customer-mds',
  runtimeLabel: 'main-candidate · abcdef1',
})));
describe('SidebarMenu', () => {
  it('shows the runtime badge in expanded mode', () => {
    render(
      <MemoryRouter>
        <SidebarMenu
          collapsed={false}
          runtimeStatus={{ mode: 'real', modeLabel: 'REAL', restartRequired: true }}
        />
      </MemoryRouter>
    );

    expect(screen.getByLabelText(/real runtime, restart required/i)).toBeInTheDocument();
    expect(screen.getByText('demo/customer-mds')).toBeInTheDocument();
  });

  it('keeps the runtime badge visible in collapsed mode', () => {
    render(
      <MemoryRouter>
        <SidebarMenu
          collapsed
          runtimeStatus={{ mode: 'real', modeLabel: 'REAL', restartRequired: true }}
        />
      </MemoryRouter>
    );

    expect(screen.getByLabelText(/real runtime, restart required/i)).toBeInTheDocument();
  });
});
