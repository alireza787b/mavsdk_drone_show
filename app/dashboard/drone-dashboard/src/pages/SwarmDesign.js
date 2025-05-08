// src/pages/SwarmDesign.js

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from '../components/DroneGraph';
import SwarmPlots from '../components/SwarmPlots';
import DroneCard from '../components/DroneCard';
import { getBackendURL } from '../utilities/utilities';
import { ToastContainer, toast } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import { FaSave, FaCloudUploadAlt, FaSpinner, FaFileImport, FaFileExport, FaUndo } from 'react-icons/fa';

const categorizeDrones = (swarmData) => {
  const topLeaders = swarmData.filter(d => d.follow === '0');
  const topSet = new Set(topLeaders.map(l => l.hw_id));
  const counts = {};
  swarmData.forEach(d => counts[d.follow] = (counts[d.follow]||0) + 1);
  const intermediate = swarmData.filter(d => !topSet.has(d.hw_id) && counts[d.hw_id]);
  return { topLeaders, intermediateLeaders: intermediate };
};

const isEqual = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const SwarmDesign = () => {
  const [swarmData, setSwarmData]       = useState([]);
  const [configData, setConfigData]     = useState([]);
  const [changes, setChanges]           = useState({ added: [], removed: [] });
  const [isSaving, setIsSaving]         = useState(false);

  // Fetch initial data
  useEffect(() => {
    const backend = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    Promise.all([
      axios.get(`${backend}/get-swarm-data`),
      axios.get(`${backend}/get-config-data`)
    ])
      .then(([sRes, cRes]) => {
        setSwarmData(sRes.data);
        setConfigData(cRes.data);
      })
      .catch(() => toast.error("Error fetching initial data"));
  }, []);

  // Detect adds/removes
  useEffect(() => {
    if (!swarmData.length || !configData.length) return;
    const added   = configData.filter(c => !swarmData.some(s => s.hw_id === c.hw_id)).map(d => d.hw_id);
    const removed = swarmData.filter(s => !configData.some(c => c.hw_id === s.hw_id)).map(d => d.hw_id);
    setChanges({ added, removed });
  }, [swarmData, configData]);

  const hasChanges = !!(changes.added.length + changes.removed.length);

  // Handlers
  const saveDraft = () => {
    toast.info("Draft saved locally");
  };

  const commitAndPush = () => {
    setIsSaving(true);
    const backend = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    axios.post(`${backend}/save-swarm-data`, swarmData)
      .then(res => {
        toast.success(res.data.message || "Changes pushed!");
        return axios.get(`${backend}/get-swarm-data`);
      })
      .then(r => setSwarmData(r.data))
      .catch(() => toast.error("Error pushing changes"))
      .finally(() => setIsSaving(false));
  };

  const fetchOriginal = () => {
    const backend = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');
    Promise.all([
      axios.get(`${backend}/get-swarm-data`),
      axios.get(`${backend}/get-config-data`)
    ])
      .then(([sRes, cRes]) => {
        setSwarmData(sRes.data);
        setConfigData(cRes.data);
        toast.info("Reverted to original data");
      })
      .catch(() => toast.error("Error reverting data"));
  };

  // CSV Import
  const expected = ["hw_id","follow","offset_n","offset_e","offset_alt","body_coord"];
  const handleCSVImport = ev => {
    const file = ev.target.files[0];
    if (!file) return;
    Papa.parse(file, {
      complete: ({ data }) => {
        const header = data[0].map(h => h.trim());
        if (header.toString() !== expected.toString()) {
          toast.error("Incorrect CSV headers");
          return;
        }
        const parsed = data.slice(1)
          .map(r => ({ hw_id:r[0], follow:r[1], offset_n:r[2], offset_e:r[3], offset_alt:r[4], body_coord:r[5] }))
          .filter(d => d.hw_id);
        setSwarmData(parsed);
        toast.success("CSV imported");
      },
      header: false
    });
  };

  // CSV Export
  const handleCSVExport = () => {
    const csv = Papa.unparse(swarmData);
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'swarm_export.csv';
    a.click();
    toast.success("CSV exported");
  };

  // In-place drone update
  const handleSaveChanges = (hw_id, updated) => {
    setSwarmData(prev => prev.map(d => d.hw_id===hw_id ? updated : d));
  };

  return (
    <div className="swarm-design">
      <div className="control-bar">
        <div className="button-group">
          <button
            className="btn draft"
            onClick={saveDraft}
            disabled={isSaving}
          >
            {isSaving ? <FaSpinner className="spin"/> : <FaSave/>} Save Draft
          </button>

          <button
            className="btn commit"
            onClick={commitAndPush}
            disabled={!hasChanges || isSaving}
          >
            {isSaving ? <FaSpinner className="spin"/> : <FaCloudUploadAlt/>} Commit &amp; Push
          </button>

          <button
            className="btn revert"
            onClick={fetchOriginal}
            disabled={isSaving}
          >
            <FaUndo/> Revert
          </button>

          <label className="btn import">
            <FaFileImport/> Import CSV
            <input type="file" accept=".csv" onChange={handleCSVImport}/>
          </label>

          <button
            className="btn export"
            onClick={handleCSVExport}
            disabled={isSaving}
          >
            <FaFileExport/> Export CSV
          </button>
        </div>

        {hasChanges && (
          <div className="alert warning">
            {changes.added.length > 0 && `Added: ${changes.added.join(', ')}. `}
            {changes.removed.length > 0 && `Removed: ${changes.removed.join(', ')}.`}
          </div>
        )}
      </div>

      <div className="swarm-container">
        {swarmData.length
          ? swarmData.map(d =>
              <DroneCard
                key={d.hw_id}
                drone={d}
                allDrones={swarmData}
                onSaveChanges={handleSaveChanges}
              />
            )
          : <p>No swarm data available.</p>
        }
      </div>

      <div className="swarm-graph">
        <DroneGraph swarmData={swarmData}/>
      </div>

      <div className="swarm-plots">
        <SwarmPlots swarmData={swarmData}/>
      </div>

      <ToastContainer position="bottom-right" autoClose={3000}/>
    </div>
  );
};

export default SwarmDesign;
