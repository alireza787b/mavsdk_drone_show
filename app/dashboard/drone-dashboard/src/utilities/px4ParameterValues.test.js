import { formatParameterValue, parseParameterValue, parameterOutcome, parameterValuesMatch } from './px4ParameterValues';

describe('PX4 value presentation and input', () => {
  it('does not coerce a missing decimal hint to zero', () => {
    expect(formatParameterValue(.123456, { value_type: 'float', decimal_places: null })).toBe('0.1235');
    expect(formatParameterValue(.123456, { value_type: 'float' })).toBe('0.1235');
    expect(formatParameterValue(0, { value_type: 'float', decimal_places: 0 })).toBe('0');
    expect(formatParameterValue(12.5, { value_type: 'float', decimal_places: 2 })).toBe('12.5');
    expect(formatParameterValue(.0000001, { value_type: 'float', decimal_places: null })).not.toBe('0');
  });
  it('retains full precision when explicitly editing or reviewing', () => {
    expect(formatParameterValue(.123456789, { value_type: 'float', decimal_places: 2 }, { exact: true })).toBe('0.123456789');
    expect(parseParameterValue('0.123456789', 'float')).toBe(.123456789);
    expect(parseParameterValue('-2e-3', 'float')).toBe(-.002);
    expect(parseParameterValue('0', 'int')).toBe(0);
    expect(parseParameterValue('  exact text  ', 'custom')).toBe('  exact text  ');
  });
  it.each(['', ' ', '12oops', '0x10', 'Infinity', 'NaN', '1e999'])('rejects incomplete or non-finite floats: %s', value => {
    expect(() => parseParameterValue(value, 'float')).toThrow();
  });
  it.each(['1.5', '3e2', '5garbage', '9007199254740992'])('rejects inexact or partial integers: %s', value => {
    expect(() => parseParameterValue(value, 'int')).toThrow();
  });
  it('never derives verified from a write acknowledgment or missing result', () => {
    expect(parameterOutcome({ applied: true, verified: false })).toBe('written_unverified');
    expect(parameterOutcome(undefined)).toBe('unknown');
    expect(parameterOutcome({ applied: false, verified: true, outcome: 'unchanged' })).toBe('unchanged');
  });
  it('uses native float identity for default/difference hints', () => {
    expect(parameterValuesMatch('float', .1, Math.fround(.1))).toBe(true);
    expect(parameterValuesMatch('float', 1e-7, 0)).toBe(false);
    expect(parameterValuesMatch('float', 1e-7, 2e-7)).toBe(false);
    expect(parameterValuesMatch('float', null, 0)).toBe(false);
  });
  it.each(['1e99', '1e-47'])('rejects unrepresentable float values before review: %s', value => {
    expect(() => parseParameterValue(value, 'float')).toThrow();
  });
  it.each(['2147483648', '-2147483649'])('rejects int32 overflow before review: %s', value => {
    expect(() => parseParameterValue(value, 'int')).toThrow();
  });
});
