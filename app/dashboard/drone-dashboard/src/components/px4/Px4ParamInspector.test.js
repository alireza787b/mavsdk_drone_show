import React from 'react';
import { render, screen } from '@testing-library/react';

import Px4ParamInspector, { buildParameterDescriptions } from './Px4ParamInspector';

const baseRow = {
  name: 'IMU_GYRO_RATEMAX',
  value_type: 'float',
  value: 400,
  default_value: 400,
  min_value: 50,
  max_value: 2000,
  unit: 'Hz',
  reboot_required: false,
  short_description: 'Gyro control data maximum publication rate.',
  long_description:
    'Gyro control data maximum publication rate. The maximum allowed output rate for controller input data.',
  docs_url: 'https://docs.px4.io/main/en/advanced_config/parameter_reference.html#IMU_GYRO_RATEMAX',
  group: 'Sensors',
  category: 'IMU',
  increment: 1,
  enum_values: [],
};

const noop = () => {};

describe('Px4ParamInspector', () => {
  test('deduplicates repeated PX4 short and long descriptions', () => {
    render(
      <Px4ParamInspector
        row={baseRow}
        draftValue="400"
        onDraftValueChange={noop}
        onResetToCurrent={noop}
        onResetToDefault={noop}
        onSave={noop}
      />
    );

    expect(screen.getAllByText(/Gyro control data maximum publication rate/i)).toHaveLength(1);
    expect(screen.getByText(/maximum allowed output rate for controller input data/i)).toBeInTheDocument();
  });

  test('preserves distinct short and long descriptions', () => {
    expect(buildParameterDescriptions({
      short_description: 'Short operator summary.',
      long_description: 'Long maintenance guidance.',
    })).toEqual({
      shortDescription: 'Short operator summary.',
      longDescription: 'Long maintenance guidance.',
    });
  });
});
