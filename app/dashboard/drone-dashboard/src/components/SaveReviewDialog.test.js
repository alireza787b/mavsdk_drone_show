import React from 'react';
import { render, screen } from '@testing-library/react';
import SaveReviewDialog from './SaveReviewDialog';

describe('SaveReviewDialog', () => {
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
