import React from 'react';
import { render, screen } from '@testing-library/react';

import ControlButtons from './ControlButtons';

const baseProps = {
  addNewDrone: jest.fn(),
  handleSaveChangesToServer: jest.fn(),
  handleRevertChanges: jest.fn(),
  handleFileChange: jest.fn(),
  exportConfig: jest.fn(),
  exportConfigCSV: jest.fn(),
  openOriginModal: jest.fn(),
  handleResetToDefault: jest.fn(),
  configData: [],
  setConfigData: jest.fn(),
  loading: false,
};

describe('ControlButtons', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('shows only secondary tools in secondary mode', () => {
    render(<ControlButtons {...baseProps} mode="secondary" />);

    expect(screen.queryByRole('button', { name: /save & commit to git/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /fleet ops sync/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /import/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /export json/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset slot assignments/i })).toBeInTheDocument();
  });

  it('links drone sync to Fleet Ops in full mode', () => {
    render(<ControlButtons {...baseProps} />);

    const link = screen.getByRole('link', { name: /fleet ops sync/i });

    expect(link).toHaveAttribute('href', '/fleet-ops');
  });
});
