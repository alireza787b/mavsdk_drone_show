import { buildQuickScoutPlanningSignature } from './quickScoutPlanningSignature';

describe('buildQuickScoutPlanningSignature', () => {
  const baseInput = {
    searchArea: [
      { lat: 37.0, lng: -122.0 },
      { lat: 37.001, lng: -122.001 },
    ],
    searchCenter: { lat: 37.0, lng: -122.0 },
    searchRadiusM: 120,
    searchPath: [
      { lat: 37.0, lng: -122.0 },
      { lat: 37.002, lng: -122.002 },
    ],
    corridorWidthM: 90,
    surveyConfig: {
      algorithm: 'boustrophedon',
      sweep_width_m: 30,
      overlap_percent: 10,
      cruise_altitude_msl: 50,
      survey_altitude_agl: 40,
      cruise_speed_ms: 10,
      survey_speed_ms: 5,
      use_terrain_following: true,
      camera_interval_s: 2,
    },
    selectedDrones: [2, 1, 2],
    missionTemplate: 'area_sweep',
    missionProfileId: 'rapid_search',
    missionLabel: 'Harbor sweep',
    missionBrief: 'Search quay perimeter',
    returnBehavior: 'hold_position',
  };

  it('normalizes selection order into a stable signature', () => {
    const first = buildQuickScoutPlanningSignature(baseInput);
    const second = buildQuickScoutPlanningSignature({
      ...baseInput,
      selectedDrones: [1, 2],
    });

    expect(first).toBe(second);
  });

  it('changes when mission-briefing inputs change', () => {
    const first = buildQuickScoutPlanningSignature(baseInput);
    const second = buildQuickScoutPlanningSignature({
      ...baseInput,
      missionLabel: 'Harbor sweep updated',
    });

    expect(first).not.toBe(second);
  });

  it('changes when the mission template changes', () => {
    const first = buildQuickScoutPlanningSignature(baseInput);
    const second = buildQuickScoutPlanningSignature({
      ...baseInput,
      missionTemplate: 'last_known_point',
    });

    expect(first).not.toBe(second);
  });

  it('changes when corridor path inputs change', () => {
    const first = buildQuickScoutPlanningSignature({
      ...baseInput,
      missionTemplate: 'corridor_search',
    });
    const second = buildQuickScoutPlanningSignature({
      ...baseInput,
      missionTemplate: 'corridor_search',
      corridorWidthM: 110,
    });

    expect(first).not.toBe(second);
  });
});
