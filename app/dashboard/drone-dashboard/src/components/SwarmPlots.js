import React, { useEffect, useMemo, useState } from 'react';
import Plot from 'react-plotly.js';
import { calculateClusterPlotData } from '../utilities/swarmDesignUtils';
import { formatCompactDroneIdentity, formatDroneLabel } from '../utilities/missionIdentityUtils';
import '../styles/SwarmPlots.css';

const plotConfig = {
  responsive: true,
  displayModeBar: false,
  staticPlot: false,
  scrollZoom: false,
};

function getThemeColors() {
  const rootStyles = getComputedStyle(document.documentElement);

  return {
    bg: rootStyles.getPropertyValue('--color-bg-primary').trim(),
    text: rootStyles.getPropertyValue('--color-text-primary').trim(),
    grid: rootStyles.getPropertyValue('--color-border-primary').trim(),
    success: rootStyles.getPropertyValue('--color-success').trim(),
    warning: rootStyles.getPropertyValue('--color-warning').trim(),
    info: rootStyles.getPropertyValue('--color-info').trim(),
    fontFamily: rootStyles.getPropertyValue('--font-family-primary').trim(),
  };
}

function getRoleColor(role, colors) {
  if (role === 'topLeader') {
    return colors.success;
  }

  if (role === 'relayLeader') {
    return colors.warning;
  }

  return colors.info;
}

function getBaseLayout(colors, isThreeDimensional = false) {
  return {
    plot_bgcolor: colors.bg,
    paper_bgcolor: colors.bg,
    font: {
      color: colors.text,
      family: colors.fontFamily,
      size: 11,
    },
    margin: { l: 52, r: 18, t: 18, b: 50 },
    showlegend: false,
    autosize: true,
    responsive: true,
    xaxis: {
      gridcolor: colors.grid,
      zerolinecolor: colors.grid,
      tickfont: { color: colors.text, size: 10 },
    },
    yaxis: {
      gridcolor: colors.grid,
      zerolinecolor: colors.grid,
      tickfont: { color: colors.text, size: 10 },
    },
    ...(isThreeDimensional
      ? {}
      : {
          hovermode: 'closest',
        }),
  };
}

function buildHoverText(points) {
  return points.map((point) => {
    const clusterPrefix = point.clusterTitle ? `${point.clusterTitle} · ` : '';
    const identity = point.title || formatCompactDroneIdentity(point.pos_id, point.hw_id, formatDroneLabel(point.hw_id));
    const secondary = point.subtitle ? ` · ${point.subtitle}` : '';
    if (point.follow === '0') {
      return `${clusterPrefix}${identity}${secondary} · Top leader`;
    }

    return `${clusterPrefix}${identity}${secondary} · Follows ${formatDroneLabel(point.follow)}`;
  });
}

function buildMarker(points, colors) {
  return {
    size: 14,
    color: points.map((point) => getRoleColor(point.role, colors)),
    opacity: 0.88,
    line: {
      color: colors.text,
      width: 1,
    },
  };
}

function PlotFrame({ title, data, layout, config = plotConfig, className = '', hasData = true }) {
  if (!hasData) {
    return (
      <div className={['plot-wrapper', className].filter(Boolean).join(' ')}>
        <div className="plot-title">{title}</div>
        <div className="plot-empty-state">Select a valid top-leader cluster to render formation analysis.</div>
      </div>
    );
  }

  return (
    <div className={['plot-wrapper', className].filter(Boolean).join(' ')}>
      <div className="plot-title">{title}</div>
      <div className="plot-content">
        <Plot
          data={data}
          layout={layout}
          config={config}
          style={{ width: '100%', height: '100%' }}
          useResizeHandler
        />
      </div>
    </div>
  );
}

function ThreeDPlot({ points }) {
  const colors = getThemeColors();

  const data = [
    {
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      z: points.map((point) => point.z),
      mode: 'markers',
      type: 'scatter3d',
      marker: {
        ...buildMarker(points, colors),
        size: 11,
      },
      hovertext: buildHoverText(points),
      hoverinfo: 'text',
    },
  ];

  const layout = {
    ...getBaseLayout(colors, true),
    scene: {
      bgcolor: colors.bg,
      camera: { eye: { x: 1.45, y: 1.4, z: 1.15 } },
      xaxis: {
        title: { text: 'East (m)', font: { color: colors.text, size: 11 } },
        gridcolor: colors.grid,
        tickfont: { color: colors.text, size: 9 },
      },
      yaxis: {
        title: { text: 'North (m)', font: { color: colors.text, size: 11 } },
        gridcolor: colors.grid,
        tickfont: { color: colors.text, size: 9 },
      },
      zaxis: {
        title: { text: 'Altitude (m)', font: { color: colors.text, size: 11 } },
        gridcolor: colors.grid,
        tickfont: { color: colors.text, size: 9 },
      },
    },
  };

  return <PlotFrame title="3D Cluster Formation" data={data} layout={layout} className="plot-3d" hasData={points.length > 0} />;
}

function NorthEastPlot({ points }) {
  const colors = getThemeColors();

  const data = [
    {
      x: points.map((point) => point.x),
      y: points.map((point) => point.y),
      mode: 'markers',
      marker: buildMarker(points, colors),
      hovertext: buildHoverText(points),
      hoverinfo: 'text',
    },
  ];

  const layout = {
    ...getBaseLayout(colors),
    xaxis: {
      ...getBaseLayout(colors).xaxis,
      title: { text: 'East (m)', font: { color: colors.text, size: 12 } },
    },
    yaxis: {
      ...getBaseLayout(colors).yaxis,
      title: { text: 'North (m)', font: { color: colors.text, size: 12 } },
    },
  };

  return <PlotFrame title="North-East View" data={data} layout={layout} hasData={points.length > 0} />;
}

function EastAltitudePlot({ points }) {
  const colors = getThemeColors();

  const data = [
    {
      x: points.map((point) => point.x),
      y: points.map((point) => point.z),
      mode: 'markers',
      marker: buildMarker(points, colors),
      hovertext: buildHoverText(points),
      hoverinfo: 'text',
    },
  ];

  const layout = {
    ...getBaseLayout(colors),
    xaxis: {
      ...getBaseLayout(colors).xaxis,
      title: { text: 'East (m)', font: { color: colors.text, size: 12 } },
    },
    yaxis: {
      ...getBaseLayout(colors).yaxis,
      title: { text: 'Altitude (m)', font: { color: colors.text, size: 12 } },
    },
  };

  return <PlotFrame title="East-Altitude View" data={data} layout={layout} hasData={points.length > 0} />;
}

function NorthAltitudePlot({ points }) {
  const colors = getThemeColors();

  const data = [
    {
      x: points.map((point) => point.y),
      y: points.map((point) => point.z),
      mode: 'markers',
      marker: buildMarker(points, colors),
      hovertext: buildHoverText(points),
      hoverinfo: 'text',
    },
  ];

  const layout = {
    ...getBaseLayout(colors),
    xaxis: {
      ...getBaseLayout(colors).xaxis,
      title: { text: 'North (m)', font: { color: colors.text, size: 12 } },
    },
    yaxis: {
      ...getBaseLayout(colors).yaxis,
      title: { text: 'Altitude (m)', font: { color: colors.text, size: 12 } },
    },
  };

  return <PlotFrame title="North-Altitude View" data={data} layout={layout} hasData={points.length > 0} />;
}

function SwarmPlots({ swarmData, configData, selectedClusterId, onSelectedClusterChange }) {
  const [activeClusterId, setActiveClusterId] = useState(selectedClusterId || null);
  const { data, clusters, description } = calculateClusterPlotData(swarmData, configData, activeClusterId);
  const clusterOptions = useMemo(
    () => (clusters.length > 0
      ? [
          {
            id: 'all',
            title: 'All executable clusters',
            counts: {
              total: clusters.reduce((sum, cluster) => sum + cluster.counts.total, 0),
            },
          },
          ...clusters,
        ]
      : []),
    [clusters]
  );

  useEffect(() => {
    if (!clusters.length) {
      if (activeClusterId !== null) {
        setActiveClusterId(null);
      }
      return;
    }

    const nextClusterId = (
      (activeClusterId && clusterOptions.some((cluster) => cluster.id === activeClusterId) && activeClusterId)
      || (selectedClusterId && clusterOptions.some((cluster) => cluster.id === selectedClusterId) && selectedClusterId)
      || clusters[0].id
    );

    if (nextClusterId !== activeClusterId) {
      setActiveClusterId(nextClusterId);
    }
  }, [activeClusterId, clusterOptions, clusters, selectedClusterId]);

  useEffect(() => {
    if (typeof onSelectedClusterChange !== 'function') {
      return;
    }

    onSelectedClusterChange(activeClusterId || null);
  }, [activeClusterId, onSelectedClusterChange]);

  return (
    <div className="swarm-plots-container">
      <div className="cluster-selection">
        <div className="cluster-selection__text">
          <strong>Formation Analysis Cluster</strong>
          <span>
            {description || 'Preview offsets relative to the selected top leader.'}
            {activeClusterId === 'all'
              ? ' Plot-only overlay mode.'
              : ' Specific cluster selections also drive cluster-scoped runtime actions.'}
          </span>
        </div>
        <select
          value={activeClusterId || ''}
          onChange={(event) => setActiveClusterId(event.target.value)}
          disabled={clusterOptions.length === 0}
        >
          {clusterOptions.length === 0 ? (
            <option value="">No valid cluster available</option>
          ) : (
            clusterOptions.map((cluster) => (
              <option key={cluster.id} value={cluster.id}>
                {cluster.title} · {cluster.counts.total} drones
              </option>
            ))
          )}
        </select>
      </div>

      <div className="plots-grid">
        <ThreeDPlot points={data} />
        <NorthEastPlot points={data} />
        <EastAltitudePlot points={data} />
        <NorthAltitudePlot points={data} />
      </div>
    </div>
  );
}

export default SwarmPlots;
