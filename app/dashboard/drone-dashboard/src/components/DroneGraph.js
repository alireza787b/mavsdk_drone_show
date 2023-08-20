import React, { useRef, useEffect } from 'react';
import CytoscapeComponent from 'react-cytoscapejs';
import '../styles/DroneGraph.css';
import { getBackendURL } from '../utilities';  // Adjust the path according to the location of utilities.js




function DroneGraph({ swarmData, onSelectDrone }) {
    const cyRef = useRef(null);
    
    const transformToGraphData = (swarmData) => {
        const nodes = swarmData.map(drone => {
            let role = 'Follower';
            if (drone.follow === '0') {
                role = 'Top Leader';
            } else if (swarmData.some(d => d.follow === drone.hw_id)) {
                role = 'Intermediate Leader';
            }
            return {
                data: { id: drone.hw_id, label: drone.hw_id, role: role, ...drone }
            };
        });
        const edges = swarmData
            .filter(drone => drone.follow !== '0')
            .map(drone => ({
                data: { source: drone.hw_id, target: drone.follow }
            }));
        return [...nodes, ...edges];
    };

    const elements = transformToGraphData(swarmData);
    const prevElementsRef = useRef(swarmData);

    useEffect(() => {
        if (cyRef.current) {
            // Update elements in the graph
            cyRef.current.batch(() => {
                cyRef.current.remove(cyRef.current.elements());
                cyRef.current.add(elements);
            });
    
            // Run the layout and fit the graph
            cyRef.current.layout(coseLayout).run();
            cyRef.current.fit();
    
            // Add a resize listener
            cyRef.current.on('resize', () => {
                cyRef.current.layout(coseLayout).run();
            });
    
            // Node click listener
            cyRef.current.on('tap', 'node', function (evt) {
                const clickedNodeId = evt.target.id();
                onSelectDrone(clickedNodeId);
                //console.log("Clicked Node ID:", clickedNodeId);

            });
    
            // Cleanup on unmount
            return () => {
                if (cyRef.current) {
                    cyRef.current.removeListener('tap', 'node');
                    cyRef.current.removeListener('resize');
                }
            };
        }
    }, [swarmData, onSelectDrone]);

    const coseLayout = {
        name: 'cose',
        directed: true,
        padding: 10,
        fit: true,
    };

    const style = {
        width: '100%',
        height: '100vh',
    };

    const styles = [
        {
            selector: 'node',
            style: {
                'label': 'data(hw_id)',
                'text-valign': 'center', 
                'text-halign': 'center',
                color: 'white'
            }
        },
        {
            selector: 'node[role="Top Leader"]',
            style: {
                'background-color': '#28a745'  // Green for Top Leader
            }
        },
        {
            selector: 'node[role="Intermediate Leader"]',
            style: {
                'background-color': '#ffcc00'  // Yellow for Intermediate Leader
            }
        },
        {
            selector: 'node[role="Follower"]',
            style: {
                'background-color': '#007bff'  // Blue for Follower
            }
        },
        {
            selector: 'edge',
            style: {
                'curve-style': 'bezier',
                'target-arrow-shape': 'triangle'
            }
        },
        {
    selector: 'node:selected',
    style: {
        'border-width': '4px',    // Add a border to the selected node
        'border-color': '#ff5733' // Color of the border (you can adjust this as desired)
    }
}

    ];
    
    return (
        <CytoscapeComponent 
            cy={(cy) => { cyRef.current = cy; }}
            elements={elements} 
            style={style}
            stylesheet={styles}
            layout={coseLayout} 
        />
    );
}

export default DroneGraph;
