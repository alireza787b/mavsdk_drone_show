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
import {
  FaSyncAlt,
  FaCloudUploadAlt,
  FaUndo,
  FaFileImport,
  FaFileExport,
} from 'react-icons/fa';

const SwarmDesign = () => {
  const [swarmData, setSwarmData] = useState([]);
  const [configData, setConfigData] = useState([]);
  const [selectedDroneId, setSelectedDroneId] = useState(null);
  const [changes, setChanges] = useState({ added: [], removed: [] });
  const [saving, setSaving] = useState(false);

  const backendURL = getBackendURL(
    process.env.REACT_APP_FLASK_PORT || '5000'
  );

  // Load both data sets once
  useEffect(() => {
    fetchOriginalData();
  }, []);

  // Compute added/removed whenever data changes
  useEffect(() => {
    if (!swarmData.length || !configData.length) return;
    const added = configData
      .filter((c) => !swarmData.some((s) => s.hw_id === c.hw_id))
      .map((c) => c.hw_id);
    const removed = swarmData
      .filter((s) => !configData.some((c) => c.hw_id === s.hw_id))
      .map((s) => s.hw_id);
    setChanges({ added, removed });
  }, [swarmData, configData]);

  const fetchOriginalData = () => {
    Promise.all([
      axios.get(`${backendURL}/get-swarm-data`),
      axios.get(`${backendURL}/get-config-data`),
    ])
      .then(([sRes, cRes]) => {
        console.log('Swarm Data:', sRes.data); // Debug log to inspect
        console.log('Config Data:', cRes.data); // Debug log to inspect
        setSwarmData(sRes.data);
        setConfigData(cRes.data);
      })
      .catch((err) => {
        console.error(err);
        toast.error('Failed to load swarm/config data');
      });
  };

  const handleSaveChanges = (hw_id, updated) => {
    setSwarmData((prev) =>
      prev.map((d) => (d.hw_id === hw_id ? updated : d))
    );
  };

  const dronesFollowing = (id) =>
    swarmData.filter((d) => d.follow === id).map((d) => d.hw_id);

  const confirmAndSave = (withCommit) => {
    const summary = swarmData
      .map((d) => {
        const role =
          d.follow === '0'
            ? 'Top Leader'
            : dronesFollowing(d.hw_id).length
            ? 'Intermediate Leader'
            : 'Follower';
        return `Drone ${d.hw_id}: ${role}${
          role !== 'Top Leader' ? ` (→ ${d.follow})` : ''
        }`;
      })
      .join('\n');

    if (
      window.confirm(
        `Would you like to ${
          withCommit ? 'commit changes' : 'update swarm data'
        }?\n\n${summary}`
      )
    ) {
      saveToServer(withCommit);
    }
  };

  const saveToServer = async (withCommit) => {
    setSaving(true);
    try {
      const url = `${backendURL}/save-swarm-data${
        withCommit ? '?commit=true' : ''
      }`;
      const res = await axios.post(url, swarmData);
      toast.success(res.data.message || 'Saved successfully');
      fetchOriginalData();
    } catch (err) {
      console.error(err);
      toast.error('Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleCSVImport = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    Papa.parse(file, {
      complete: ({ data }) => {
        const header = data[0].map((h) => h.trim());
        const expected = [
          'hw_id',
          'follow',
          'offset_n',
          'offset_e',
          'offset_alt',
          'body_coord',
        ];
        if (header.toString() !== expected.toString()) {
          toast.error('Invalid CSV header');
          return;
        }
        const parsed = data
          .slice(1)
          .map((r) => ({
            hw_id: r[0],
            follow: r[1],
            offset_n: r[2],
            offset_e: r[3],
            offset_alt: r[4],
            body_coord: r[5],
          }))
          .filter((d) => d.hw_id);
        setSwarmData(parsed);
        toast.success('CSV imported');
      },
      header: false,
    });
  };

  const handleCSVExport = () => {
    const csv = Papa.unparse(swarmData);
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'swarm_export.csv';
    link.click();
    toast.success('CSV exported');
  };

  const handleRevert = () => {
    if (window.confirm('Revert all unsaved changes?')) {
      fetchOriginalData();
    }
  };

  return (
    <div className="swarm-design-container">
      {/* Top Controls */}
      <div className="controls">
        <div className="primary-actions">
          <button
            className="btn update"
            onClick={() => confirmAndSave(false)}
            disabled={saving}
          >
            <FaSyncAlt /> Update Swarm
          </button>
          <button
            className="btn commit"
            onClick={() => confirmAndSave(true)}
            disabled={saving}
          >
            <FaCloudUploadAlt /> Commit Changes
          </button>
        </div>
        <div className="secondary-actions">
          <button
            className="btn revert"
            onClick={handleRevert}
            disabled={saving}
          >
            <FaUndo /> Revert
          </button>
          <label className="btn import">
            <FaFileImport /> Import CSV
            <input
              type="file"
              accept=".csv"
              onChange={handleCSVImport}
            />
          </label>
          <button
            className="btn export"
            onClick={handleCSVExport}
            disabled={saving}
          >
            <FaFileExport /> Export CSV
          </button>
        </div>
      </div>

      {/* Inline Add/Remove Notification */}
      {(changes.added.length || changes.removed.length) && (
        <div className="notification">
          {changes.added.length > 0 && (
            <span>Added: {changes.added.join(', ')}</span>
          )}
          {changes.removed.length > 0 && (
            <span>Removed: {changes.removed.join(', ')}</span>
          )}
        </div>
      )}

      {/* Main Content */}
      <div className="main-content">
        {/* Left: Drone Cards List */}
        <div className="left-panel">
          {swarmData.length ? (
            swarmData.map((d) => (
              <DroneCard
                key={d.hw_id}
                drone={d}
                allDrones={swarmData}
                onSaveChanges={handleSaveChanges}
                isSelected={selectedDroneId === d.hw_id}
              />
            ))
          ) : (
            <p className="empty">No configuration available</p>
          )}
        </div>

        {/* Right: Live Graph */}
        <div className="right-panel">
          <DroneGraph
            swarmData={swarmData}
            onSelectDrone={setSelectedDroneId}
          />
        </div>
      </div>

      {/* Bottom: Plots */}
      <div className="plots-section">
        <SwarmPlots swarmData={swarmData} />
      </div>

      {/* Toast Notifications */}
      <ToastContainer position="bottom-right" autoClose={3000} />
    </div>
  );
};

export default SwarmDesign;
