import React, { useEffect, useRef } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import '../styles/DroneGraph.css';

function buildGraphElements(drones) {
  const nodes = drones.map((drone) => ({
    data: {
      id: drone.hw_id,
      label: formatCompactDroneIdentity(drone.pos_id, drone.hw_id, `H${drone.hw_id}`),
      role: drone.role,
      warningState: drone.hasWarnings ? 'attention' : 'clear',
      roleSwapState: drone.isRoleSwap ? 'swap' : 'native',
    },
  }));

  const edges = drones
    .filter((drone) => drone.follow !== '0' && drone.followTargetExists && drone.follow !== drone.hw_id)
    .map((drone) => ({
      data: {
        id: `${drone.follow}-${drone.hw_id}`,
        source: drone.follow,
        target: drone.hw_id,
        frame: drone.frame,
      },
    }));

  return [...nodes, ...edges];
}

function applySelectionClasses(cy, selectedDroneId) {
  cy.nodes().removeClass('is-selected is-upstream is-downstream');
  cy.edges().removeClass('is-upstream is-downstream');

  if (!selectedDroneId) {
    return;
  }

  const node = cy.getElementById(String(selectedDroneId));
  if (!node || node.length === 0) {
    return;
  }

  node.addClass('is-selected');
  node.predecessors().addClass('is-upstream');
  node.successors().addClass('is-downstream');
}

function DroneGraph({ swarmData, selectedDroneId, onSelectDrone }) {
  const cyRef = useRef(null);

  const graphElements = buildGraphElements(swarmData);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return undefined;
    }
    const topLeaderIds = swarmData
      .filter((drone) => drone.role === 'topLeader')
      .map((drone) => drone.hw_id);

    cy.batch(() => {
      cy.elements().remove();
      cy.add(graphElements);
    });

    cy.layout({
      name: 'breadthfirst',
      directed: true,
      padding: 24,
      spacingFactor: 1.15,
      animate: false,
      fit: true,
      roots: topLeaderIds,
    }).run();

    cy.fit(undefined, 36);

    return undefined;
  }, [graphElements, swarmData]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return undefined;
    }

    applySelectionClasses(cy, selectedDroneId);
    return undefined;
  }, [selectedDroneId]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return undefined;
    }

    const handleTap = (event) => {
      onSelectDrone(event.target.id());
    };

    cy.on('tap', 'node', handleTap);

    return () => {
      cy.removeListener('tap', 'node', handleTap);
    };
  }, [onSelectDrone]);

  const stylesheet = [
    {
      selector: 'node',
      style: {
        'shape': 'ellipse',
        'width': 70,
        'height': 70,
        'background-color': '#1e90ff',
        'border-width': 2,
        'border-color': '#8abfff',
        'label': 'data(label)',
        'font-size': 11,
        'font-weight': 700,
        'text-valign': 'center',
        'text-halign': 'center',
        'text-wrap': 'wrap',
        'text-max-width': 66,
        'color': '#f7fbff',
        'transition-property': 'background-color, border-color, border-width, width, height',
        'transition-duration': '150ms',
      },
    },
    {
      selector: 'node[role = "topLeader"]',
      style: {
        'shape': 'round-rectangle',
        'width': 84,
        'height': 64,
        'background-color': '#169b62',
        'border-color': '#76d3ac',
      },
    },
    {
      selector: 'node[role = "relayLeader"]',
      style: {
        'shape': 'hexagon',
        'background-color': '#e0a100',
        'border-color': '#ffe18c',
        'color': '#1f2128',
      },
    },
    {
      selector: 'node[warningState = "attention"]',
      style: {
        'border-width': 4,
        'border-color': '#ff866b',
      },
    },
    {
      selector: 'node[roleSwapState = "swap"]',
      style: {
        'border-style': 'dashed',
      },
    },
    {
      selector: 'edge',
      style: {
        'curve-style': 'bezier',
        'width': 3,
        'line-color': '#77849b',
        'target-arrow-color': '#77849b',
        'target-arrow-shape': 'triangle',
        'arrow-scale': 1.1,
      },
    },
    {
      selector: 'edge[frame = "body"]',
      style: {
        'line-style': 'dashed',
        'line-color': '#ff9f43',
        'target-arrow-color': '#ff9f43',
      },
    },
    {
      selector: 'node.is-selected',
      style: {
        'width': 92,
        'height': 92,
        'border-width': 6,
        'border-color': '#00d4ff',
        'overlay-color': '#00d4ff',
        'overlay-opacity': 0.08,
      },
    },
    {
      selector: 'node.is-upstream, edge.is-upstream',
      style: {
        'background-color': '#5cc7ff',
        'border-color': '#9de0ff',
        'line-color': '#5cc7ff',
        'target-arrow-color': '#5cc7ff',
        'opacity': 1,
      },
    },
    {
      selector: 'node.is-downstream, edge.is-downstream',
      style: {
        'background-color': '#8abfff',
        'border-color': '#cfe5ff',
        'line-color': '#8abfff',
        'target-arrow-color': '#8abfff',
        'opacity': 1,
      },
    },
    {
      selector: 'node, edge',
      style: {
        'opacity': 0.95,
      },
    },
  ];

  return (
    <div className="swarm-graph-shell">
      <CytoscapeComponent
        cy={(cy) => {
          cyRef.current = cy;
        }}
        elements={graphElements}
        layout={{ name: 'preset' }}
        stylesheet={stylesheet}
        style={{ width: '100%', height: '100%' }}
        minZoom={0.3}
        maxZoom={2.4}
      />
    </div>
  );
}

export default DroneGraph;
