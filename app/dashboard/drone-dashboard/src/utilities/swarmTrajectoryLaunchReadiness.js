const countLabel = (count = 0, singular, plural = `${singular}s`) => `${count} ${count === 1 ? singular : plural}`;

const countClusterIssues = (clusters = []) => clusters.reduce((total, cluster) => total + (cluster.issues?.length || 0), 0);
const countClusterAdvisories = (clusters = []) => clusters.reduce((total, cluster) => total + (cluster.advisories?.length || 0), 0);

export const buildSwarmTrajectoryLaunchReadiness = ({
  clusterStatus = null,
  loading = false,
  error = null,
} = {}) => {
  const blockers = [];
  const warnings = [];

  if (loading) {
    blockers.push('Verifying the processed Swarm Trajectory package...');
  }

  if (error) {
    blockers.push('Swarm Trajectory readiness could not be verified from the backend.');
  }

  const clusters = clusterStatus?.clusters || [];
  const summary = clusterStatus?.cluster_summary || {};
  const session = clusterStatus?.session || { exists: false };
  const clusterCount = summary.cluster_count ?? clusters.length;
  const readyClusterCount = summary.ready_cluster_count ?? clusters.filter((cluster) => cluster.ready).length;
  const needsProcessingCount = summary.needs_processing_cluster_count ?? clusters.filter((cluster) => cluster.state === 'needs_processing').length;
  const partialOutputCount = summary.partial_output_cluster_count ?? clusters.filter((cluster) => cluster.state === 'partial_outputs').length;
  const missingUploadCount = summary.missing_upload_cluster_count ?? clusters.filter((cluster) => !cluster.leader_uploaded).length;
  const processedDroneCount = clusterStatus?.processed_drones?.length ?? clusterStatus?.processed_trajectories ?? 0;
  const expectedDroneCount = session.total_drones
    || clusters.reduce(
      (count, cluster) => count + (cluster.expected_drone_count ?? ((cluster.follower_count || 0) + 1)),
      0,
    );
  const issueCount = countClusterIssues(clusters);
  const advisoryCount = countClusterAdvisories(clusters);
  const orphanLeaderCount = clusterStatus?.orphan_uploaded_leaders?.length || 0;

  if (!loading && !error) {
    if (clusterCount === 0) {
      blockers.push('No swarm clusters are configured. Publish the hierarchy in Swarm Design first.');
    }

    if (!session.exists || processedDroneCount === 0) {
      blockers.push('No processed Swarm Trajectory package is active yet.');
    }

    if (missingUploadCount > 0) {
      blockers.push(`${countLabel(missingUploadCount, 'leader upload')} still ${missingUploadCount === 1 ? 'is' : 'are'} missing.`);
    }

    if (needsProcessingCount > 0) {
      blockers.push(`${countLabel(needsProcessingCount, 'cluster')} still ${needsProcessingCount === 1 ? 'needs' : 'need'} a processing pass.`);
    }

    if (partialOutputCount > 0) {
      blockers.push(`${countLabel(partialOutputCount, 'cluster')} still ${partialOutputCount === 1 ? 'has' : 'have'} partial outputs.`);
    }

    if (clusterCount > 0 && readyClusterCount < clusterCount && missingUploadCount === 0 && needsProcessingCount === 0 && partialOutputCount === 0) {
      blockers.push('The processed package is incomplete and not all clusters are marked ready.');
    }

    if (issueCount > 0) {
      blockers.push(`${countLabel(issueCount, 'cluster issue')} still ${issueCount === 1 ? 'requires' : 'require'} operator correction before launch.`);
    }

    if (advisoryCount > 0) {
      warnings.push(`${countLabel(advisoryCount, 'advisory item')} should be reviewed before launch.`);
    }

    if (orphanLeaderCount > 0) {
      warnings.push(`${countLabel(orphanLeaderCount, 'uploaded leader path')} no longer ${orphanLeaderCount === 1 ? 'belongs' : 'belong'} to the current swarm structure.`);
    }
  }

  return {
    blockers,
    warnings,
    canLaunch: blockers.length === 0,
    summary: {
      clusterCount,
      readyClusterCount,
      needsProcessingCount,
      partialOutputCount,
      missingUploadCount,
      processedDroneCount,
      expectedDroneCount,
      issueCount,
      advisoryCount,
      session,
      overallState: summary.overall_state || 'unknown',
    },
  };
};
