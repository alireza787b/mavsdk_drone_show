// src/components/logs/LogViewerToolbar.test.js
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import LogViewerToolbar from './LogViewerToolbar';
import { MODES } from '../../constants/logConstants';

describe('LogViewerToolbar', () => {
  const defaultProps = {
    mode: MODES.OPS,
    onModeChange: jest.fn(),
    level: 'WARNING',
    onLevelChange: jest.fn(),
    paused: false,
    onTogglePause: jest.fn(),
    connected: true,
    searchQuery: '',
    onSearchChange: jest.fn(),
    sessions: [],
    selectedSession: null,
    onSessionSelect: jest.fn(),
    sessionsLoading: false,
    onExportOpen: jest.fn(),
    onOnboardUlogOpen: jest.fn(),
    onClear: jest.fn(),
    scopeDroneId: null,
    scopeOptions: [{ hw_id: 5, pos_id: 12, label: 'P12|H5' }],
    onScopeChange: jest.fn(),
    liveWindow: 'all',
    onLiveWindowChange: jest.fn(),
    timeStart: '',
    onTimeStartChange: jest.fn(),
    timeEnd: '',
    onTimeEndChange: jest.fn(),
    onClearTimeRange: jest.fn(),
  };

  test('renders Ops and Dev mode buttons', () => {
    render(<LogViewerToolbar {...defaultProps} />);
    expect(screen.getByText('Ops')).toBeInTheDocument();
    expect(screen.getByText('Dev')).toBeInTheDocument();
  });

  test('clicking Dev button calls onModeChange', () => {
    render(<LogViewerToolbar {...defaultProps} />);
    fireEvent.click(screen.getByText('Dev'));
    expect(defaultProps.onModeChange).toHaveBeenCalledWith(MODES.DEV);
  });

  test('shows search input only in Dev mode', () => {
    const { rerender } = render(<LogViewerToolbar {...defaultProps} />);
    expect(screen.queryByPlaceholderText('Search logs...')).not.toBeInTheDocument();
    rerender(<LogViewerToolbar {...defaultProps} mode={MODES.DEV} />);
    expect(screen.getByPlaceholderText('Search logs...')).toBeInTheDocument();
  });

  test('shows Export button only in Dev mode', () => {
    const { rerender } = render(<LogViewerToolbar {...defaultProps} />);
    expect(screen.queryByText('Export')).not.toBeInTheDocument();
    rerender(<LogViewerToolbar {...defaultProps} mode={MODES.DEV} />);
    expect(screen.getByText('Export')).toBeInTheDocument();
  });

  test('renders scope selector options', () => {
    render(<LogViewerToolbar {...defaultProps} />);
    expect(screen.getByLabelText('Select log scope')).toBeInTheDocument();
    expect(screen.getByText('P12|H5')).toBeInTheDocument();
  });

  test('shows absolute time range inputs for historical sessions', () => {
    render(<LogViewerToolbar {...defaultProps} selectedSession="s_20260320_072832" />);
    expect(screen.getByLabelText('Filter logs from time')).toBeInTheDocument();
    expect(screen.getByLabelText('Filter logs to time')).toBeInTheDocument();
  });

  test('hides live buffer clear button for historical sessions', () => {
    render(<LogViewerToolbar {...defaultProps} selectedSession="s_20260320_072832" />);
    expect(screen.queryByTitle('Clear live buffer')).not.toBeInTheDocument();
  });

  test('shows onboard ULog button only when a drone scope is selected', () => {
    const { rerender } = render(<LogViewerToolbar {...defaultProps} />);
    expect(screen.queryByText('ULog')).not.toBeInTheDocument();

    rerender(<LogViewerToolbar {...defaultProps} scopeDroneId={5} />);
    expect(screen.getByText('ULog')).toBeInTheDocument();
  });

  test('clicking onboard ULog button calls the handler', () => {
    render(<LogViewerToolbar {...defaultProps} scopeDroneId={5} />);

    fireEvent.click(screen.getByText('ULog'));

    expect(defaultProps.onOnboardUlogOpen).toHaveBeenCalled();
  });
});
