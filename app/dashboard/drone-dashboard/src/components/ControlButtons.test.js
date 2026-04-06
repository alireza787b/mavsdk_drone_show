import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import ControlButtons from './ControlButtons';

const mockSyncDrones = jest.fn();

jest.mock('../hooks/useSyncDrones', () => ({
  useSyncDrones: () => ({
    syncing: false,
    syncDrones: mockSyncDrones,
  }),
}));

const baseProps = {
  addNewDrone: jest.fn(),
  handleSaveChangesToServer: jest.fn(),
  handleRevertChanges: jest.fn(),
  handleFileChange: jest.fn(),
  exportConfig: jest.fn(),
  exportConfigCSV: jest.fn(),
  openOriginModal: jest.fn(),
  openGcsConfigModal: jest.fn(),
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
    expect(screen.queryByRole('button', { name: /sync drones/i })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /import/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /export json/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /reset slot assignments/i })).toBeInTheDocument();
  });

  it('keeps sync drones available in full mode', () => {
    render(<ControlButtons {...baseProps} />);

    fireEvent.click(screen.getByRole('button', { name: /sync drones/i }));

    expect(mockSyncDrones).toHaveBeenCalledTimes(1);
  });
});
