import React, { useState } from 'react';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import MoreActionsPanel from './MoreActionsPanel';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../../constants/droneConstants';

const originalShowModal = HTMLDialogElement.prototype.showModal;
const originalClose = HTMLDialogElement.prototype.close;
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = jest.fn(function open() { this.setAttribute('open', ''); });
  HTMLDialogElement.prototype.close = jest.fn(function close() { this.removeAttribute('open'); });
});
afterEach(() => {
  cleanup();
  if (originalShowModal) HTMLDialogElement.prototype.showModal = originalShowModal;
  else delete HTMLDialogElement.prototype.showModal;
  if (originalClose) HTMLDialogElement.prototype.close = originalClose;
  else delete HTMLDialogElement.prototype.close;
});

const defaults = () => ({
  targetCount: 2, targetLabel: 'Scout · H1, Survey · H7', runtimeMode: 'real',
  referenceNowMs: 1_700_000_000_000, onSendCommand: jest.fn(),
  onRequestPrecisionMove: jest.fn(), canPrecisionMove: false, onClose: jest.fn(),
});

function Harness(props) {
  const [open, setOpen] = useState(false);
  return <><button type="button" onClick={() => setOpen(true)}>More</button>
    {open && <MoreActionsPanel {...props} onClose={() => { props.onClose(); setOpen(false); }} />}</>;
}

test('native modal exposes the exact supplied target scope and runtime without primary-control duplication', () => {
  const props = defaults();
  render(<MoreActionsPanel {...props} />);
  const dialog = screen.getByRole('dialog', { name: 'More actions' });
  expect(dialog).toHaveAttribute('aria-modal', 'true');
  expect(dialog).toHaveAccessibleDescription('2 aircraft Scout · H1, Survey · H7 REAL');
  expect(dialog.parentElement).toBe(document.body);
  expect(HTMLDialogElement.prototype.showModal).toHaveBeenCalledTimes(1);
  expect(within(dialog).queryByRole('button', { name: /^take off\./i })).not.toBeInTheDocument();
  expect(within(dialog).queryByRole('button', { name: /^hold position\./i })).not.toBeInTheDocument();
  expect(within(dialog).getByRole('button', { name: /precision move/i })).toBeDisabled();
});

test('commands only produce review intents and do not manufacture targets or physical acknowledgements', () => {
  const props = defaults();
  render(<MoreActionsPanel {...props} />);
  fireEvent.click(screen.getByRole('button', { name: /arm\/disarm ground test/i }));
  expect(props.onSendCommand).toHaveBeenLastCalledWith(expect.objectContaining({ mission_type: DRONE_ACTION_TYPES.TEST, trigger_time: 0 }));
  expect(props.onSendCommand.mock.calls[0][0]).not.toHaveProperty('ground_test_safety');
  expect(props.onSendCommand.mock.calls[0][0]).not.toHaveProperty('target_drone_ids');
  fireEvent.click(screen.getByRole('button', { name: /cancel mission/i }));
  expect(props.onSendCommand).toHaveBeenLastCalledWith(expect.objectContaining({ mission_type: DRONE_MISSION_TYPES.NONE, trigger_time: 0 }));
  expect(props.onClose).not.toHaveBeenCalled();
});

test('Move uses the caller-owned flow only when explicitly eligible', () => {
  const props = { ...defaults(), canPrecisionMove: true };
  render(<MoreActionsPanel {...props} />);
  fireEvent.click(screen.getByRole('button', { name: /precision move/i }));
  expect(props.onRequestPrecisionMove).toHaveBeenCalledTimes(1);
  expect(props.onSendCommand).not.toHaveBeenCalled();
});

test('unknown runtime blocks the motor-arm test', () => {
  const props = { ...defaults(), runtimeMode: 'unknown' };
  render(<MoreActionsPanel {...props} />);
  const button = screen.getByRole('button', { name: /arm\/disarm ground test/i });
  expect(button).toBeDisabled();
  fireEvent.click(button);
  expect(props.onSendCommand).not.toHaveBeenCalled();
});

test('Tab wraps within the dialog without focusing collapsed advanced controls', () => {
  render(<MoreActionsPanel {...defaults()} />);
  const dialog = screen.getByRole('dialog', { name: 'More actions' });
  const close = within(dialog).getByRole('button', { name: 'Close more actions' });
  const summary = within(dialog).getByText('Advanced timing').closest('summary');
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, { key: 'Tab', shiftKey: true });
  expect(summary).toHaveFocus();
  fireEvent.keyDown(summary, { key: 'Tab' });
  expect(close).toHaveFocus();
});

test.each(['Escape', 'cancel', 'backdrop', 'close button'])('%s dismisses and restores trigger focus', (method) => {
  const props = defaults();
  render(<Harness {...props} />);
  const trigger = screen.getByRole('button', { name: 'More' });
  trigger.focus();
  fireEvent.click(trigger);
  const dialog = screen.getByRole('dialog', { name: 'More actions' });
  if (method === 'Escape') fireEvent.keyDown(dialog, { key: 'Escape' });
  else if (method === 'cancel') fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
  else if (method === 'backdrop') fireEvent.click(dialog);
  else fireEvent.click(within(dialog).getByRole('button', { name: 'Close more actions' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(props.onClose).toHaveBeenCalledTimes(1);
  expect(trigger).toHaveFocus();
});

test('clicking dialog content does not dismiss it', () => {
  const props = defaults();
  render(<MoreActionsPanel {...props} />);
  fireEvent.click(screen.getByRole('heading', { name: 'More actions' }));
  expect(props.onClose).not.toHaveBeenCalled();
});
