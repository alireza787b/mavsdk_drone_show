import {
  COMMAND_CATALOG,
  COMMAND_METADATA_BY_KEY,
  COMMAND_METADATA_BY_VALUE,
  getCommandMetadata,
} from './missionCatalog';
import missionIdentities from '../generated/missionIdentities.generated.json';

const missionValueByKey = Object.fromEntries(
  missionIdentities.map(({ key, value }) => [key, value]),
);

describe('missionCatalog', () => {
  test('has one unique identity record for every backend mission enum value', () => {
    const expectedIdentities = Object.fromEntries(
      missionIdentities.map(({ key, value }) => [key, value]),
    );

    expect(Object.fromEntries(COMMAND_CATALOG.map(({ key, value }) => [key, value])))
      .toEqual(expectedIdentities);
    expect(Object.keys(COMMAND_METADATA_BY_KEY)).toHaveLength(COMMAND_CATALOG.length);
    expect(Object.keys(COMMAND_METADATA_BY_VALUE)).toHaveLength(COMMAND_CATALOG.length);
  });

  test('keeps telemetry and command wording explicit without parallel name tables', () => {
    expect(getCommandMetadata('NONE')).toMatchObject({
      commandLabel: 'Cancel Mission',
      statusLabel: 'No Mission',
    });
    expect(getCommandMetadata(missionValueByKey.TEST).statusLabel).toBe('Arm/Disarm Ground Test');
    expect(getCommandMetadata(String(missionValueByKey.HOVER_TEST)).statusLabel).toBe('Automated Hover Flight');
    expect(getCommandMetadata('TAKE_OFF').value).toBe(missionValueByKey.TAKE_OFF);
  });

  test('does not advertise an unimplemented disarm command', () => {
    expect(COMMAND_METADATA_BY_KEY.DISARM).toBeUndefined();
  });
});
