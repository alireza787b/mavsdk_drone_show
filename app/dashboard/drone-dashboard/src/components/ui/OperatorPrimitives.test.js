import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import {
  ActionIconButton,
  ConfirmDialog,
  DocsLink,
  EmptyState,
  MetricStrip,
  OperatorNotice,
  PageActionBar,
  PageShell,
  StatusBadge,
} from './OperatorPrimitives';

describe('operator UI primitives', () => {
  test('renders compact page shell with route-aware docs link', () => {
    render(
      <PageShell
        eyebrow="System"
        title="Fleet Ops"
        subtitle="Node posture"
        docsRoute="/fleet-ops"
        docsOptions={{ repoUrl: 'git@github.com:demo/customer-mds.git', branch: 'main-candidate' }}
      >
        <div>Body</div>
      </PageShell>
    );

    expect(screen.getByRole('heading', { name: 'Fleet Ops' })).toBeInTheDocument();
    expect(screen.getByText('Node posture')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /fleet ops guide/i })).toHaveAttribute(
      'aria-label',
      'Fleet ops guide'
    );
    expect(screen.getByRole('link', { name: /fleet ops guide/i })).toHaveAttribute(
      'href',
      'https://github.com/demo/customer-mds/blob/main-candidate/docs/guides/fleet-ops.md'
    );
  });

  test('renders status and metric primitives with accessible summaries', () => {
    render(
      <>
        <StatusBadge tone="success">Ready</StatusBadge>
        <MetricStrip
          label="Fleet summary"
          items={[
            { key: 'online', label: 'Online', value: 4, detail: 'all links' },
            { key: 'ready', label: 'Ready', value: '4/4', tone: 'success' },
          ]}
        />
      </>
    );

    expect(screen.getAllByText('Ready')).toHaveLength(2);
    expect(screen.getByRole('list', { name: 'Fleet summary' })).toBeInTheDocument();
    expect(screen.getByText('4/4')).toBeInTheDocument();
  });

  test('renders icon actions without native title dependency', () => {
    const onClick = jest.fn();
    render(
      <ActionIconButton icon={<span>!</span>} label="Open fleet guide" onClick={onClick}>
        Guide
      </ActionIconButton>
    );

    const button = screen.getByRole('button', { name: 'Open fleet guide' });
    expect(button).not.toHaveAttribute('title');
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  test('groups primary and secondary page actions with a mobile overflow affordance', () => {
    render(
      <PageActionBar
        primary={<button type="button">Commit</button>}
        secondary={<button type="button">Export</button>}
      />
    );

    expect(screen.getByRole('button', { name: 'Commit' })).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'Export' })).toHaveLength(2);
    expect(screen.getByText('More')).toBeInTheDocument();
  });

  test('renders notices and empty states as compact operator surfaces', () => {
    render(
      <>
        <OperatorNotice tone="warning" title="Runtime restart required">
          Apply restart before changing mode.
        </OperatorNotice>
        <EmptyState title="No matching drones" detail="Clear filters to see the full fleet." />
      </>
    );

    expect(screen.getByRole('status')).toHaveTextContent('Runtime restart required');
    expect(screen.getByRole('heading', { name: 'No matching drones' })).toBeInTheDocument();
  });

  test('confirm dialog confirms, cancels, and closes on escape', () => {
    const onConfirm = jest.fn();
    const onCancel = jest.fn();
    const { rerender } = render(
      <ConfirmDialog
        open
        title="Restart GCS?"
        message="Runtime mode changes require restart."
        confirmLabel="Restart"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Restart' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(
      <ConfirmDialog
        open={false}
        title="Restart GCS?"
        message="Runtime mode changes require restart."
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    );
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  test('docs link returns null when no route metadata exists', () => {
    const { container } = render(<DocsLink route="/missing-route" />);
    expect(container).toBeEmptyDOMElement();
  });
});
