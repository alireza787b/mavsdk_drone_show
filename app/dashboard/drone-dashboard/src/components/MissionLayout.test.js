import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import MissionLayout from './MissionLayout';
import { generateKML } from '../utilities/missionConfigUtilities';

jest.mock('../utilities/missionConfigUtilities', () => ({
  generateKML: jest.fn(() => '<kml />'),
}));

jest.mock('./OriginModal', () => {
  function MockOriginModal({ isOpen }) {
    return isOpen ? <div data-testid="origin-modal">Origin modal</div> : null;
  }

  return MockOriginModal;
});

describe('MissionLayout', () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalAnchorClick = HTMLAnchorElement.prototype.click;

  beforeEach(() => {
    URL.createObjectURL = jest.fn(() => 'blob:test-kml');
    HTMLAnchorElement.prototype.click = jest.fn();
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  afterAll(() => {
    URL.createObjectURL = originalCreateObjectURL;
    HTMLAnchorElement.prototype.click = originalAnchorClick;
  });

  test('accepts zero-valued origin coordinates for KML export', () => {
    render(
      <MissionLayout
        configData={[]}
        origin={{ lat: 0, lon: 0 }}
        openOriginModal={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /export to google earth/i }));

    expect(generateKML).toHaveBeenCalledWith([], 0, 0);
    expect(screen.queryByTestId('origin-modal')).not.toBeInTheDocument();
  });
});
