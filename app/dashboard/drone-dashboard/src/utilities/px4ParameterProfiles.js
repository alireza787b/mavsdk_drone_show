export function buildMdsParameterProfileFile(profile) {
  const profileId = profile?.profile_id || 'px4-profile';
  const sanitizedProfileId = String(profileId).trim() || 'px4-profile';
  const filename = `${sanitizedProfileId}.json`;
  const payload = {
    profile_id: sanitizedProfileId,
    name: profile?.name || sanitizedProfileId,
    description: profile?.description || '',
    recommended_scope: profile?.recommended_scope || 'fleet',
    tags: Array.isArray(profile?.tags) ? profile.tags : [],
    entries: Array.isArray(profile?.entries) ? profile.entries : [],
  };

  return {
    filename,
    text: `${JSON.stringify(payload, null, 2)}\n`,
  };
}
