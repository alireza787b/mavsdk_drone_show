import React from 'react';
import { render, screen } from '@testing-library/react';
import TrajectoryDialogPortal from './TrajectoryDialogPortal';

describe('TrajectoryDialogPortal', () => {
  it('renders outside transformed workspace ancestry and restores background scrolling', () => {
    const previousOverflow = document.body.style.overflow;
    const { unmount } = render(<div style={{ transform: 'translateX(0)' }}><TrajectoryDialogPortal>
      <section role="dialog">Editor dialog</section>
    </TrajectoryDialogPortal></div>);
    expect(screen.getByRole('dialog').closest('.trajectory-dialog-host').parentElement).toBe(document.body);
    expect(document.body.style.overflow).toBe('hidden');
    unmount();
    expect(document.body.style.overflow).toBe(previousOverflow);
  });

  it('keeps scrolling locked until the final editor dialog closes', () => {
    const previousOverflow = document.body.style.overflow;
    const first = render(<TrajectoryDialogPortal><section>First dialog</section></TrajectoryDialogPortal>);
    const second = render(<TrajectoryDialogPortal><section>Second dialog</section></TrajectoryDialogPortal>);
    first.unmount();
    expect(document.body.style.overflow).toBe('hidden');
    second.unmount();
    expect(document.body.style.overflow).toBe(previousOverflow);
  });
});
