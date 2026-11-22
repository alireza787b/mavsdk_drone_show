import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { alertCondition, InlineAlerts } from './AlertAnnunciators';

test('exact duplicate findings count once, the higher current severity wins, and prior findings do not count', () => {
  const entries = [
    { ...alertCondition('1', 'Scout', 'Heading unstable'), observed: true },
    alertCondition('1', 'Scout', '  heading unstable  ', { tone: 'danger', source: 'PX4' }),
    alertCondition('2', 'Wing', 'Heading unstable'),
  ];
  const lastReported = [alertCondition('1', 'Scout', 'Low battery', { tone: 'danger', source: 'PX4' })];
  render(<InlineAlerts entries={entries} lastReported={lastReported} label="Takeoff alerts" />);
  const warning = screen.getByRole('button', { name: 'Warning: 1' });
  expect(screen.getByRole('button', { name: 'Caution: 1' })).toBeInTheDocument();
  fireEvent.click(warning);
  const current = screen.getByRole('list', { name: 'Current alerts' });
  expect(within(current).getAllByRole('listitem')).toHaveLength(1);
  expect(within(current).getByText('PX4')).toBeInTheDocument();
  expect(current).not.toHaveTextContent('Low battery');
  fireEvent.click(screen.getByRole('button', { name: 'Close alert details' }));
  expect(warning).toHaveFocus();
  expect(screen.queryByRole('region', { name: 'Takeoff alerts' })).not.toBeInTheDocument();
});
