const MAV_PARAM_TYPES = Object.freeze({
  int: 6,
  float: 9,
});

export function buildQgcParameterFile(snapshotResponse) {
  const snapshot = snapshotResponse?.snapshot || {};
  const rows = Array.isArray(snapshotResponse?.rows) ? snapshotResponse.rows : [];
  const exportableRows = [];
  const skippedRows = [];

  rows.forEach((row) => {
    const typeId = MAV_PARAM_TYPES[row?.value_type];
    if (!typeId) {
      skippedRows.push(row?.name || 'UNKNOWN');
      return;
    }

    exportableRows.push([
      snapshot.hw_id || 1,
      row.component_id || snapshot.component_id || 1,
      row.name,
      row.value,
      typeId,
    ].join('\t'));
  });

  return {
    filename: `px4-params-${snapshot.hw_id || 'drone'}-${snapshot.snapshot_id || 'snapshot'}.params`,
    skippedRows,
    text: [
      '# QGroundControl Parameter File',
      '# Vehicle-Id\tComponent-Id\tName\tValue\tType',
      ...exportableRows,
      '',
    ].join('\n'),
  };
}
