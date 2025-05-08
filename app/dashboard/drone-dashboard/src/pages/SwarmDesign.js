import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Papa from 'papaparse';
import '../styles/SwarmDesign.css';
import DroneGraph from '../components/DroneGraph';
import SwarmPlots from '../components/SwarmPlots';
import DroneCard from '../components/DroneCard';
import { getBackendURL } from '../utilities/utilities';
import { FaSyncAlt, FaCloudUploadAlt } from 'react-icons/fa';  // For icons
import { toast } from 'react-toastify';  // For toast notifications

const categorizeDrones = (swarmData) => {
    const topLeaders = swarmData.filter(drone => drone.follow === '0');
    const topLeaderIdsSet = new Set(topLeaders.map(leader => leader.hw_id));

    const followerCounts = {};
    swarmData.forEach(drone => {
        if (!followerCounts[drone.follow]) {
            followerCounts[drone.follow] = 0;
        }
        followerCounts[drone.follow]++;
    });

    const intermediateLeaders = swarmData.filter(drone =>
        !topLeaderIdsSet.has(drone.hw_id) && followerCounts[drone.hw_id]
    );

    return {
        topLeaders,
        intermediateLeaders
    };
};

const isEqual = (arr1, arr2) => JSON.stringify(arr1) === JSON.stringify(arr2);

const SwarmDesign = () => {
    const [swarmData, setSwarmData] = useState([]);
    const [configData, setConfigData] = useState([]);
    const [selectedDroneId, setSelectedDroneId] = useState(null);
    const [changes, setChanges] = useState({ added: [], removed: [] });
    const [saving, setSaving] = useState(false);

    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    // Initial fetch of both datasets
    useEffect(() => {
        const fetchSwarmData = axios.get(`${backendURL}/get-swarm-data`);
        const fetchConfigData = axios.get(`${backendURL}/get-config-data`);
        Promise.all([fetchSwarmData, fetchConfigData])
            .then(([swarmRes, configRes]) => {
                setSwarmData(swarmRes.data);
                setConfigData(configRes.data);
            })
            .catch(err => {
                console.error('Error fetching data:', err);
                toast.error('Failed to fetch swarm or config data.');
            });
    }, []);

    // Merge config + swarm, detect adds/removes
    useEffect(() => {
        if (swarmData.length === 0 || configData.length === 0) return;

        let merged = [...swarmData];

        const added = configData
            .filter(c => !swarmData.some(s => s.hw_id === c.hw_id))
            .map(c => c.hw_id);
        const removed = swarmData
            .filter(s => !configData.some(c => c.hw_id === s.hw_id))
            .map(s => s.hw_id);
        setChanges({ added, removed });

        configData.forEach(c => {
            if (!swarmData.some(s => s.hw_id === c.hw_id)) {
                merged.push({
                    hw_id: c.hw_id,
                    follow: '0',
                    offset_n: '0',
                    offset_e: '0',
                    offset_alt: '0',
                    body_coord: '0'
                });
            }
        });

        merged = merged.filter(s => configData.some(c => c.hw_id === s.hw_id));

        if (!isEqual(merged, swarmData)) {
            setSwarmData(merged);
        }
    }, [configData, swarmData]);

    const handleSaveChanges = (hw_id, updated) => {
        setSwarmData(prev => prev.map(d => d.hw_id === hw_id ? updated : d));
    };

    const dronesFollowing = leaderId =>
        swarmData.filter(d => d.follow === leaderId).map(d => d.hw_id);

    const confirmAndSave = withCommit => {
        const summary = swarmData.map(d => {
            const role = d.follow === '0'
                ? 'Top Leader'
                : dronesFollowing(d.hw_id).length
                ? 'Intermediate Leader'
                : 'Follower';
            return `Drone ${d.hw_id}: ${role}${role !== 'Top Leader' ? ` (→${d.follow})` : ''}`;
        }).join('\n');

        if (window.confirm(`Proceed to ${withCommit ? 'commit' : 'update'} swarm?\n\n${summary}`)) {
            saveSwarmData(withCommit);
        }
    };

    const saveSwarmData = async withCommit => {
        setSaving(true);
        try {
            const url = `${backendURL}/save-swarm-data${withCommit ? '?commit=true' : '?commit=false'}`;
            const res = await axios.post(url, swarmData);
            toast.success(res.data.message || 'Saved successfully.');
            // re-fetch
            const [swRes, cfgRes] = await Promise.all([
                axios.get(`${backendURL}/get-swarm-data`),
                axios.get(`${backendURL}/get-config-data`)
            ]);
            setSwarmData(swRes.data);
            setConfigData(cfgRes.data);
        } catch (err) {
            console.error('Save failed:', err);
            toast.error('Save failed.');
        } finally {
            setSaving(false);
        }
    };

    const handleCSVImport = e => {
        const file = e.target.files[0];
        if (!file) return;
        Papa.parse(file, {
            complete: ({ data }) => {
                const header = data[0].map(h => h.trim());
                const expected = ["hw_id", "follow", "offset_n", "offset_e", "offset_alt", "body_coord"];
                if (header.toString() !== expected.toString()) {
                    return toast.error('CSV header mismatch.');
                }
                const parsed = data.slice(1)
                    .map(r => ({
                        hw_id: r[0], follow: r[1],
                        offset_n: r[2], offset_e: r[3],
                        offset_alt: r[4], body_coord: r[5]
                    }))
                    .filter(d => d.hw_id);
                setSwarmData(parsed);
            },
            header: false
        });
    };

    const handleCSVExport = () => {
        const csv = Papa.unparse(swarmData);
        const blob = new Blob([csv], { type: 'text/csv' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = 'swarm_export.csv';
        link.click();
    };

    const handleRevert = () => {
        if (window.confirm('Revert all changes?')) {
            window.location.reload();
        }
    };

    return (
        <div className="swarm-design-container">
            <div className="control-buttons">
                {/* Update Swarm and Commit Changes Buttons */}
                <div className="button-group">
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
                    <button
                        className="btn revert"
                        onClick={handleRevert}
                        disabled={saving}
                    >
                        Revert
                    </button>
                </div>

                <div className="button-group">
                    <label className="btn import">
                        Import CSV
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
                        Export CSV
                    </button>
                </div>
            </div>

            

            <div className="main-content">
                {/* Drone Cards */}
                <div className="left-panel">
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

                {/* Graph */}
                <div className="right-panel">
                    <DroneGraph
                        swarmData={swarmData}
                        onSelectDrone={setSelectedDroneId}
                    />
                </div>
            </div>

            <div className="swarm-plots-container">
                <SwarmPlots swarmData={swarmData} />
            </div>
            {(changes.added.length || changes.removed.length) && (
                <div className="notification-container">
                    {changes.added.length > 0 && <span>Added: {changes.added.join(', ')}</span>}
                    {changes.removed.length > 0 && <span>Removed: {changes.removed.join(', ')}</span>}
                </div>
            )}
        </div>
    );
};

export default SwarmDesign;
