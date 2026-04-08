export const QUICKSCOUT_PROFILE_PRESETS = [
  {
    id: 'rapid_search',
    label: 'Rapid Search',
    brief: 'Fast initial coverage for time-sensitive assessment.',
    surveyConfig: {
      algorithm: 'boustrophedon',
      sweep_width_m: 40,
      overlap_percent: 8,
      cruise_altitude_msl: 55,
      survey_altitude_agl: 45,
      cruise_speed_ms: 12,
      survey_speed_ms: 7,
      use_terrain_following: true,
      camera_interval_s: 2.5,
    },
  },
  {
    id: 'detailed_sweep',
    label: 'Detailed Sweep',
    brief: 'Tighter spacing and slower legs for confirmation passes.',
    surveyConfig: {
      algorithm: 'boustrophedon',
      sweep_width_m: 24,
      overlap_percent: 18,
      cruise_altitude_msl: 48,
      survey_altitude_agl: 35,
      cruise_speed_ms: 9,
      survey_speed_ms: 4.5,
      use_terrain_following: true,
      camera_interval_s: 1.5,
    },
  },
  {
    id: 'wide_area_screen',
    label: 'Wide Area',
    brief: 'Broader coverage when area size matters more than detail.',
    surveyConfig: {
      algorithm: 'boustrophedon',
      sweep_width_m: 55,
      overlap_percent: 5,
      cruise_altitude_msl: 65,
      survey_altitude_agl: 55,
      cruise_speed_ms: 13,
      survey_speed_ms: 8,
      use_terrain_following: true,
      camera_interval_s: 3,
    },
  },
];

export const DEFAULT_QUICKSCOUT_PROFILE_ID = QUICKSCOUT_PROFILE_PRESETS[0].id;

export const deriveQuickScoutProfileId = (surveyConfig = {}) => {
  const matchedProfile = QUICKSCOUT_PROFILE_PRESETS.find((profile) =>
    Object.entries(profile.surveyConfig).every(([key, value]) => surveyConfig?.[key] === value)
  );
  return matchedProfile?.id || 'custom';
};

export const getQuickScoutProfile = (profileId) =>
  QUICKSCOUT_PROFILE_PRESETS.find((profile) => profile.id === profileId) || null;
