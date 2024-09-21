// app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.jsx

import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import PropTypes from 'prop-types';

function InitialLaunchPlot({ drones, onDroneClick }) {
  // Memoize parsed values to optimize performance
  const plotData = useMemo(() => {
    return drones.map((drone) => ({
      x: parseFloat(drone.x),
      y: parseFloat(drone.y),
      hw_id: drone.hw_id,
      pos_id: drone.pos_id,
    }));
  }, [drones]);

  const plotMarkers = useMemo(() => {
    return {
      x: plotData.map((drone) => drone.x),
      y: plotData.map((drone) => drone.y),
      text: plotData.map((drone) => `Drone ${drone.hw_id} (Pos ID: ${drone.pos_id})`),
      type: 'scatter',
      mode: 'markers+text',
      marker: {
        size: 16,
        color: '#3498db', // Bright blue
        opacity: 0.8,
        line: {
          color: '#1A5276',  // Dark blue border
          width: 2,
        },
      },
      textfont: {
        color: 'white',
        size: 14,
      },
      textposition: 'middle center',
      hoverinfo: 'text+x+y',  // Show text along with X and Y
      name: 'Drones',
    };
  }, [plotData]);

  const layout = useMemo(() => ({
    title: 'Initial Launch Positions',
    xaxis: {
      title: 'North (X)',
      zeroline: false,
    },
    yaxis: {
      title: 'East (Y)',
      zeroline: false,
    },
    hovermode: 'closest',
    hoverlabel: {
      bgcolor: '#1A5276',
      font: {
        color: 'white',
      },
    },
    margin: { t: 50, l: 50, r: 50, b: 50 },
    autosize: true,
    responsive: true,
  }), []);

  const handleClick = (data) => {
    if (data.points && data.points.length > 0) {
      const clickedPoint = data.points[0];
      const clickedDroneHwId = drones[clickedPoint.pointIndex].hw_id;
      onDroneClick(clickedDroneHwId);

      // Scroll to the corresponding DroneConfigCard using React refs
      const element = document.querySelector(`.drone-config-card[data-hw-id="${clickedDroneHwId}"]`);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    }
  };

  return (
    <div className="initial-launch-plot">
      <Plot
        data={[plotMarkers]}
        layout={layout}
        onClick={handleClick}
        style={{ width: '100%', height: '100%' }}
        useResizeHandler={true}
      />
    </div>
  );
}

InitialLaunchPlot.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string.isRequired,
    pos_id: PropTypes.string.isRequired,
    x: PropTypes.string.isRequired,
    y: PropTypes.string.isRequired,
    ip: PropTypes.string.isRequired,
    mavlink_port: PropTypes.string.isRequired,
    debug_port: PropTypes.string.isRequired,
    gcs_ip: PropTypes.string.isRequired,
  })).isRequired,
  onDroneClick: PropTypes.func.isRequired,
};

export default InitialLaunchPlot;
