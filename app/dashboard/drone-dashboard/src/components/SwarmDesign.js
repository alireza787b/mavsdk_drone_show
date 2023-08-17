import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';


function SwarmDesign() {
    const [swarmData, setSwarmData] = useState([]);
    const [configData, setConfigData] = useState([]);

    useEffect(() => {
        // Fetch and parse swarm.csv
        axios.get('http://localhost:5000/get-swarm-data')
      .then(response => {
          setSwarmData(response.data);
      })
      .catch(error => {
          console.error("Error fetching swarm data:", error);
      });


      // Fetch and parse config.csv
      axios.get('http://localhost:5000/get-config-data')
      .then(response => {
          setConfigData(response.data);
      })
      .catch(error => {
          console.error("Error fetching config data:", error);
      });




          
    }, []);

    return (
        <div>
            {/* Your 3D and 2D visualization logic will go here */}
        </div>
    );
}

export default SwarmDesign;
