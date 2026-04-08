function normalizePoint(point = {}) {
  const lat = Number(point?.lat);
  const lng = Number(point?.lng);

  return {
    lat: Number.isFinite(lat) ? lat : null,
    lng: Number.isFinite(lng) ? lng : null,
  };
}

function normalizeSurveyConfig(surveyConfig = {}) {
  const orderedKeys = [
    'algorithm',
    'sweep_width_m',
    'overlap_percent',
    'cruise_altitude_msl',
    'survey_altitude_agl',
    'cruise_speed_ms',
    'survey_speed_ms',
    'use_terrain_following',
    'camera_interval_s',
  ];

  return orderedKeys.reduce((result, key) => {
    const value = surveyConfig?.[key];
    if (value === undefined) {
      return result;
    }

    result[key] = typeof value === 'number' ? Number(value) : value;
    return result;
  }, {});
}

function normalizeIds(values = []) {
  return [...new Set(
    (Array.isArray(values) ? values : [])
      .map((value) => Number(value))
      .filter((value) => Number.isFinite(value)),
  )].sort((left, right) => left - right);
}

export function buildQuickScoutPlanningSignature({
  missionTemplate = 'area_sweep',
  searchArea = [],
  searchCenter = null,
  searchRadiusM = null,
  surveyConfig = {},
  selectedDrones = [],
  missionProfileId = '',
  missionLabel = '',
  missionBrief = '',
  returnBehavior = 'return_home',
} = {}) {
  return JSON.stringify({
    missionTemplate: String(missionTemplate || 'area_sweep').trim(),
    searchArea: (Array.isArray(searchArea) ? searchArea : []).map(normalizePoint),
    searchCenter: searchCenter ? normalizePoint(searchCenter) : null,
    searchRadiusM: Number.isFinite(Number(searchRadiusM)) ? Number(searchRadiusM) : null,
    surveyConfig: normalizeSurveyConfig(surveyConfig),
    selectedDrones: normalizeIds(selectedDrones),
    missionProfileId: String(missionProfileId || '').trim(),
    missionLabel: String(missionLabel || '').trim(),
    missionBrief: String(missionBrief || '').trim(),
    returnBehavior: String(returnBehavior || 'return_home').trim(),
  });
}

export default buildQuickScoutPlanningSignature;
