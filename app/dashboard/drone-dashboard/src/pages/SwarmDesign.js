import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from '../components/DroneGraph';
import SwarmPlots from '../components/SwarmPlots';
import DroneCard from '../components/DroneCard';
import { getBackendURL } from '../utilities/utilities';

const SwarmDesign = () => {
    const [swarmData, setSwarmData] = useState([]);
    const [configData, setConfigData] = useState([]);
    const [selectedDroneId, setSelectedDroneId] = useState(null);
    const [changes, setChanges] = useState({ added: [], removed: [] });
    const [saving, setSaving] = useState(false);

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    useEffect(() => {
        fetchOriginalSwarmData();
    }, []);

    useEffect(() => {
        if (swarmData.length === 0 || configData.length === 0) return;

        let updatedSwarmData = [...swarmData];

        const addedDrones = configData.filter(configDrone =>
            !swarmData.some(drone => drone.hw_id === configDrone.hw_id)
        ).map(drone => drone.hw_id);

        const removedDrones = swarmData.filter(swarmDrone =>
            !configData.some(configDrone => configDrone.hw_id === swarmDrone.hw_id)
        ).map(drone => drone.hw_id);

        setChanges({ added: addedDrones, removed: removedDrones });

        configData.forEach(configDrone => {
            if (!swarmData.some(drone => drone.hw_id === configDrone.hw_id)) {
                updatedSwarmData.push({
                    hw_id: configDrone.hw_id,
                    follow: '0',
                    offset_n: '0',
                    offset_e: '0',
                    offset_alt: '0',
                    body_coord: '0'
                });
            }
        });

        updatedSwarmData = updatedSwarmData.filter(swarmDrone =>
            configData.some(configDrone => configDrone.hw_id === swarmDrone.hw_id)
        );

        setSwarmData(updatedSwarmData);
    }, [configData]);

    const handleSaveChanges = (hw_id, updatedDroneData) => {
        setSwarmData(prev => prev.map(drone => drone.hw_id === hw_id ? updatedDroneData : drone));
    };

    const fetchOriginalSwarmData = () => {
        const fetchSwarmData = axios.get(`${backendURL}/get-swarm-data`);
        const fetchConfigData = axios.get(`${backendURL}/get-config-data`);

        Promise.all([fetchSwarmData, fetchConfigData])
            .then(([swarmRes, configRes]) => {
                setSwarmData(swarmRes.data);
                setConfigData(configRes.data);
            })
            .catch(console.error);
    };

    const dronesFollowing = (leaderId) =>
        swarmData.filter(drone => drone.follow === leaderId).map(drone => drone.hw_id);

    const confirmAndSave = (withCommit = false) => {
        const summary = swarmData.map(drone => {
            const role = drone.follow === '0'
                ? 'Top Leader'
                : dronesFollowing(drone.hw_id).length
                ? 'Intermediate Leader'
                : 'Follower';
            return `Drone ${drone.hw_id}: ${role}${role !== 'Top Leader' ? ` (Follows Drone ${drone.follow})` : ''} with Offsets N:${drone.offset_n} E:${drone.offset_e} Alt:${drone.offset_alt}`;
        }).join('\n');

        if (window.confirm(`Confirm ${withCommit ? 'permanent' : 'temporary'} save?\n\n${summary}`)) {
            saveSwarmDataToServer(withCommit);
        }
    };

    const saveSwarmDataToServer = async (withCommit) => {
        setSaving(true);
        try {
            const endpoint = `${backendURL}/save-swarm-data${withCommit ? '?commit=true' : ''}`;
            const response = await axios.post(endpoint, swarmData);
            alert(response.data.message || 'Swarm data saved.');
            fetchOriginalSwarmData();
        } catch (err) {
            console.error(err);
            alert('Save failed.');
        } finally {
            setSaving(false);
        }
    };

    const handleCSVImport = (event) => {
        const file = event.target.files[0];
        if (file) {
            Papa.parse(file, {
                complete: (result) => {
                    const header = result.data[0].map(c => c.trim());
                    const expected = ["hw_id", "follow", "offset_n", "offset_e", "offset_alt", "body_coord"];
                    if (header.toString() !== expected.toString()) {
                        alert("Invalid CSV header format.");
                        return;
                    }
                    const parsedData = result.data.slice(1).map(row => ({
                        hw_id: row[0],
                        follow: row[1],
                        offset_n: row[2],
                        offset_e: row[3],
                        offset_alt: row[4],
                        body_coord: row[5]
                    })).filter(d => d.hw_id);
                    setSwarmData(parsedData);
                },
                header: false
            });
        }
    };

    const handleCSVExport = () => {
        const csv = Papa.unparse(swarmData);
        const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement("a");
        link.href = URL.createObjectURL(blob);
        link.download = "swarm_export.csv";
        link.click();
    };

    const handleRevert = () => {
        if (window.confirm("Revert all unsaved changes?")) {
            fetchOriginalSwarmData();
        }
    };

    return (
        <div className="swarm-design-container">
            <div className={`control-buttons ${changes.added.length > 0 || changes.removed.length > 0 ? 'show-notification' : ''}`}>
                {(changes.added.length > 0 || changes.removed.length > 0) && (
                    <div className="notification-container">
                        <span className="notification-icon">⚠️</span>
                        <p className="notification-text">
                            {changes.added.length > 0 && `Added: ${changes.added.join(', ')}`}
                            {changes.removed.length > 0 && ` | Removed: ${changes.removed.join(', ')}`}
                        </p>
                    </div>
                )}

                <div className="primary-actions">
                    <button className="btn-draft" onClick={() => confirmAndSave(false)} disabled={saving}>
                        Save Draft
                    </button>
                    <button className="btn-commit" onClick={() => confirmAndSave(true)} disabled={saving}>
                        Save & Push
                    </button>
                </div>

                <div className="secondary-actions">
                    <button className="revert" onClick={handleRevert}>Revert</button>
                    <label className="file-upload-btn">
                        Import CSV
                        <input type="file" accept=".csv" onChange={handleCSVImport} />
                    </label>
                    <button className="export-config" onClick={handleCSVExport}>Export CSV</button>
                </div>
            </div>

            <div className="swarm-container">
                {swarmData.length ? swarmData.map(drone => (
                    <DroneCard
                        key={drone.hw_id}
                        drone={drone}
                        allDrones={swarmData}
                        onSaveChanges={handleSaveChanges}
                        isSelected={selectedDroneId === drone.hw_id}
                    />
                )) : <p>No data available for swarm configuration.</p>}
            </div>

            <div className="swarm-graph-container">
                <DroneGraph swarmData={swarmData} onSelectDrone={setSelectedDroneId} />
            </div>

            <div className="swarm-plots-container">
                <SwarmPlots swarmData={swarmData} />
            </div>
        </div>
    );
};

export default SwarmDesign;
