import {
  DEFAULT_QUICKSCOUT_PROFILE_ID,
  deriveQuickScoutProfileId,
  getQuickScoutProfile,
  QUICKSCOUT_PROFILE_PRESETS,
} from './quickScoutProfiles';

describe('quickScoutProfiles', () => {
  it('returns the configured default profile', () => {
    expect(DEFAULT_QUICKSCOUT_PROFILE_ID).toBe(QUICKSCOUT_PROFILE_PRESETS[0].id);
  });

  it('finds a preset by id', () => {
    expect(getQuickScoutProfile('rapid_search')?.label).toBe('Rapid Search');
    expect(getQuickScoutProfile('missing')).toBeNull();
  });

  it('derives the preset id from matching survey config values', () => {
    expect(deriveQuickScoutProfileId(QUICKSCOUT_PROFILE_PRESETS[1].surveyConfig)).toBe('detailed_sweep');
    expect(deriveQuickScoutProfileId({ sweep_width_m: 99 })).toBe('custom');
  });
});
