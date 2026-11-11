import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import SaveReviewDialog from './SaveReviewDialog';

describe('SaveReviewDialog', () => {
  const report = () => ({ warnings: { duplicate_hw_ids: [], duplicates: [{ pos_id: 1, hw_ids: [1, 2] }], missing_trajectories: [], role_swaps: [] },
    changes: { pos_id_changes: [] }, summary: { total_drones: 2, pos_id_changes_count: 0, duplicates_count: 1 } });
  test('a changed review cannot inherit acknowledgment, and blocking errors stay blocked', () => {
    const onConfirm = jest.fn(), onCancel = jest.fn();
    const props = { isOpen: true, validationReport: report(), onConfirm, onCancel };
    const view = render(<SaveReviewDialog {...props} />);
    expect(screen.getByRole('button', { name: 'Confirm and Save' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: 'Confirm and Save' })).toBeEnabled();
    const replacement = report();
    replacement.warnings.missing_trajectories = [{ hw_id: 2, pos_id: 2, message: 'Missing' }];
    view.rerender(<SaveReviewDialog {...props} validationReport={replacement} />);
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByRole('button', { name: 'Confirm and Save' })).toBeDisabled();
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalled();
  });
  test('explains that role swaps are slot-only changes and not spare replacement', () => {
    render(
      <SaveReviewDialog
        isOpen
        validationReport={{
          warnings: {
            duplicate_hw_ids: [],
            duplicates: [],
            missing_trajectories: [],
            role_swaps: [{ hw_id: 5, pos_id: 6 }],
          },
          changes: {
            pos_id_changes: [{ hw_id: 5, old_pos_id: 5, new_pos_id: 6 }],
          },
          summary: {
            total_drones: 2,
            pos_id_changes_count: 1,
            duplicate_hw_ids_count: 0,
            duplicates_count: 0,
          },
        }}
        onConfirm={jest.fn()}
        onCancel={jest.fn()}
      />
    );

    expect(screen.getByText(/use slot edits only for role ownership inside the current fleet/i)).toBeInTheDocument();
    expect(screen.getByText(/fleet enrollment → replace existing slot/i)).toBeInTheDocument();
    expect(screen.getByText(/they do not replace fleet hardware and they do not rewrite smart swarm follow-links/i)).toBeInTheDocument();
  });
});
