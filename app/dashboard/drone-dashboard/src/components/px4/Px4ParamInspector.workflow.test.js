import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import Px4ParamInspector from './Px4ParamInspector';

const row = { name: 'TEST_FLOAT', value_type: 'float', value: .123456789, decimal_places: 2, component_id: 1,
  default_value: 0, metadata_authority: 'reference_only', enum_values: Array.from({ length: 12 }, (_, index) => ({ value: index, description: `Choice ${index}` })) };

test('starts read-only, edits exact precision, and never truncates declared reference choices', () => {
  const stage = jest.fn(() => true);
  render(<Px4ParamInspector row={row} aircraftLabel="Aircraft · H1" onClose={jest.fn()} onStage={stage} />);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  expect(screen.getByRole('textbox', { name: 'New value for TEST_FLOAT' })).toHaveValue('0.123456789');
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  expect(stage).toHaveBeenCalledWith({ component_id: 1, name: 'TEST_FLOAT', value_type: 'float', value: .123456789 });
  expect(screen.getByText('Choice 11')).toBeInTheDocument();
});
test('keeps an edit through snapshot replacement and rejects partial numeric input', () => {
  const stage = jest.fn();
  const props = { aircraftLabel: 'H1', onClose: jest.fn(), onStage: stage };
  const view = render(<Px4ParamInspector row={row} {...props} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'New value for TEST_FLOAT' }), { target: { value: '2.5junk' } });
  view.rerender(<Px4ParamInspector row={{ ...row, value: .5 }} {...props} />);
  expect(screen.getByRole('textbox', { name: 'New value for TEST_FLOAT' })).toHaveValue('2.5junk');
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  expect(stage).not.toHaveBeenCalled();
  expect(screen.getByRole('alert')).toHaveTextContent('Enter a finite number');
});
test('shared dialog supports Escape and restores the opener focus', () => {
  const close = jest.fn();
  render(<Px4ParamInspector row={row} aircraftLabel="H1" onClose={close} onStage={jest.fn()} />);
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(close).toHaveBeenCalledTimes(1);
});

const enumRow = { ...row, name: 'TEST_ENUM', value_type: 'int', value: 2, metadata_authority: 'vehicle', authoritative_fields: ['enum_values'] };

test('authoritative enum editor exposes every label and numeric code, then stages the chosen code', () => {
  const stage = jest.fn(() => true);
  render(<Px4ParamInspector row={enumRow} aircraftLabel="H1" onClose={jest.fn()} onStage={stage} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  const editor = screen.getByRole('combobox', { name: 'New value for TEST_ENUM' });
  expect(editor).toHaveValue('2');
  expect(screen.getByRole('option', { name: 'Choice 11 · 11' })).toBeInTheDocument();
  expect(editor.options).toHaveLength(12);
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
  fireEvent.change(editor, { target: { value: '11' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  expect(stage).toHaveBeenCalledWith({ component_id: 1, name: 'TEST_ENUM', value_type: 'int', value: 11 });
});

test('unknown current enum value and draft survive refresh without selecting a replacement', () => {
  const stage = jest.fn(() => true);
  const props = { aircraftLabel: 'H1', onClose: jest.fn(), onStage: stage };
  const view = render(<Px4ParamInspector row={{ ...enumRow, value: 99 }} {...props} />);
  expect(screen.getByText('99')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  expect(screen.getByRole('combobox', { name: 'New value for TEST_ENUM' })).toHaveValue('99');
  expect(screen.getByRole('option', { name: 'Not declared by vehicle · 99' })).toBeInTheDocument();
  view.rerender(<Px4ParamInspector row={{ ...enumRow, value: 1 }} {...props} />);
  expect(screen.getByRole('combobox', { name: 'New value for TEST_ENUM' })).toHaveValue('99');
  expect(stage).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'New value for TEST_ENUM' }), { target: { value: '3' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  expect(stage).toHaveBeenCalledWith(expect.objectContaining({ value: 3 }));
});

test.each(['reference_only', 'unavailable'])('%s enum hints remain optional suggestions and never restrict raw values', authority => {
  const stage = jest.fn(() => true);
  render(<Px4ParamInspector row={{ ...enumRow, metadata_authority: authority, authoritative_fields: [] }} aircraftLabel="H1" onClose={jest.fn()} onStage={stage} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  const raw = screen.getByRole('textbox', { name: 'New value for TEST_ENUM' });
  expect(raw).toHaveValue('2');
  fireEvent.click(screen.getByText('Reference choices'));
  const suggestions = screen.getByRole('combobox', { name: 'Reference choice for TEST_ENUM' });
  expect(screen.getByRole('option', { name: 'Choice 11 · 11' })).toBeInTheDocument();
  fireEvent.change(suggestions, { target: { value: '11' } });
  expect(raw).toHaveValue('11');
  fireEvent.change(raw, { target: { value: '99' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  expect(stage).toHaveBeenCalledWith(expect.objectContaining({ value: 99 }));
});

test('unknown metadata without declared choices keeps the exact raw editor', () => {
  render(<Px4ParamInspector row={{ ...row, enum_values: [], metadata_authority: 'unavailable', authoritative_fields: [] }} aircraftLabel="H1" onClose={jest.fn()} onStage={jest.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  expect(screen.getByRole('textbox', { name: 'New value for TEST_FLOAT' })).toHaveValue('0.123456789');
  expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
});
