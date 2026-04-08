import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import FindingReviewPanel from './FindingReviewPanel';

describe('FindingReviewPanel', () => {
  it('renders empty copy when no finding is selected', () => {
    render(
      <FindingReviewPanel
        finding={null}
        saving={false}
        deleting={false}
        onSaveFinding={() => {}}
        onDeleteFinding={() => {}}
      />
    );

    expect(screen.getByText('Select a finding to review, classify, and update operator notes.')).toBeInTheDocument();
  });

  it('delegates save and delete actions through container callbacks', () => {
    const onSaveFinding = jest.fn();
    const onDeleteFinding = jest.fn();
    const onFocusFinding = jest.fn();
    const onSeedFollowUpFromFinding = jest.fn();

    render(
      <FindingReviewPanel
        finding={{
          id: 'finding-1',
          summary: 'Unreviewed observation',
          type: 'other',
          priority: 'medium',
          confidence: 'medium',
          source: 'operator_mark',
          status: 'new',
          notes: '',
        }}
        saving={false}
        deleting={false}
        onSaveFinding={onSaveFinding}
        onDeleteFinding={onDeleteFinding}
        onFocusFinding={onFocusFinding}
        onSeedFollowUpFromFinding={onSeedFollowUpFromFinding}
      />
    );

    fireEvent.change(screen.getByLabelText('Summary'), {
      target: { value: 'Confirmed vessel contact' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Center Map' }));
    fireEvent.click(screen.getByRole('button', { name: 'Follow-up Search' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Finding' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));

    expect(onSaveFinding).toHaveBeenCalledWith(
      'finding-1',
      expect.objectContaining({
        summary: 'Confirmed vessel contact',
        type: 'other',
        priority: 'medium',
      }),
    );
    expect(onDeleteFinding).toHaveBeenCalledWith('finding-1');
    expect(onFocusFinding).toHaveBeenCalledWith(expect.objectContaining({ id: 'finding-1' }));
    expect(onSeedFollowUpFromFinding).toHaveBeenCalledWith(expect.objectContaining({ id: 'finding-1' }));
  });
});
