import React, { useState, useEffect } from 'react';
import axios from 'axios';
import '../styles/MissionConfig.css';
import InitialLaunchPlot from './InitialLaunchPlot';




function MissionConfig() {
    const [configData, setConfigData] = useState([]);
    const [editingDroneId, setEditingDroneId] = useState(null);

    const allHwIds = new Set(configData.map(drone => parseInt(drone.hw_id)));
    const maxHwId = Math.max(0, ...allHwIds) + 1; // Added default value of 0 for Math.max
    const availableHwIds = Array.from({ length: maxHwId }, (_, i) => i + 1).filter(id => !allHwIds.has(id));

    useEffect(() => {
        // Fetch config data
        axios.get('http://localhost:5000/get-config-data')
            .then(response => {
                setConfigData(response.data);
            })
            .catch(error => {
                console.error("Error fetching config data:", error);
            });
    }, []);

        useEffect(() => {
            // Fetch config data
            axios.get('http://localhost:5000/get-config-data')
                .then(response => {
                    setConfigData(response.data);
                })
                .catch(error => {
                    console.error("Error fetching config data:", error);
                });
        }, []);

        // This will map through the configData and generate a card for each drone's configuration
        const sortedConfigData = [...configData].sort((a, b) => a.hw_id - b.hw_id);
        const droneCards = sortedConfigData.map(drone => (
        <div className="drone-config-card droneCard" key={drone.hw_id} data-hw-id={drone.hw_id}>
                <h4>Drone {drone.hw_id}</h4>
                <hr />
                {editingDroneId === drone.hw_id ? (
                    <>
                        {/* This is the editing view with input fields */}
                        <label htmlFor={`hw_id-${drone.hw_id}`}>Hardware ID:</label>
                        <select id={`hw_id-${drone.hw_id}`} defaultValue={drone.hw_id}>
                            <option value={drone.hw_id}>{drone.hw_id}</option>
                            {availableHwIds.map(id => <option key={id} value={id}>{id}</option>)}
                        </select>
        
                        <label htmlFor={`ip-${drone.hw_id}`}>IP Address:</label>
                        <input type="text" id={`ip-${drone.hw_id}`} defaultValue={drone.ip} placeholder="Enter IP Address" />
        
                        <label htmlFor={`mavlink_port-${drone.hw_id}`}>MavLink Port:</label>
                        <input type="text" id={`mavlink_port-${drone.hw_id}`} defaultValue={drone.mavlink_port} placeholder="Enter MavLink Port" />
        
                        <label htmlFor={`debug_port-${drone.hw_id}`}>Debug Port:</label>
                        <input type="text" id={`debug_port-${drone.hw_id}`} defaultValue={drone.debug_port} placeholder="Enter Debug Port" />
        
                        <label htmlFor={`gcs_ip-${drone.hw_id}`}>GCS IP:</label>
                        <input type="text" id={`gcs_ip-${drone.hw_id}`} defaultValue={drone.gcs_ip} placeholder="Enter GCS IP Address" />
        
                        <label htmlFor={`x-${drone.hw_id}`}>Initial X:</label>
                        <input type="text" id={`x-${drone.hw_id}`} defaultValue={drone.x} placeholder="Enter Initial X Coordinate" />
        
                        <label htmlFor={`y-${drone.hw_id}`}>Initial Y:</label>
                        <input type="text" id={`y-${drone.hw_id}`} defaultValue={drone.y} placeholder="Enter Initial Y Coordinate" />
        
                        <label htmlFor={`pos_id-${drone.hw_id}`}>Position ID:</label>
                        <input type="text" id={`pos_id-${drone.hw_id}`} defaultValue={drone.pos_id} placeholder="Enter Position ID" />
        
                        <button onClick={() => saveChanges(drone.hw_id, {
                            hw_id: document.querySelector(`#hw_id-${drone.hw_id}`).value,
                            ip: document.querySelector(`#ip-${drone.hw_id}`).value,
                            mavlink_port: document.querySelector(`#mavlink_port-${drone.hw_id}`).value,
                            debug_port: document.querySelector(`#debug_port-${drone.hw_id}`).value,
                            gcs_ip: document.querySelector(`#gcs_ip-${drone.hw_id}`).value,
                            x: document.querySelector(`#x-${drone.hw_id}`).value,
                            y: document.querySelector(`#y-${drone.hw_id}`).value,
                            pos_id: document.querySelector(`#pos_id-${drone.hw_id}`).value
                        })}>Save</button>
                        <button onClick={() => setEditingDroneId(null)}>Cancel</button>
                    </>
                ) : (
                    <>
                        {/* This is the default view */}
                        <p><strong>IP:</strong> {drone.ip}</p>
                        <p><strong>MavLink Port:</strong> {drone.mavlink_port}</p>
                        <p><strong>Debug Port:</strong> {drone.debug_port}</p>
                        <p><strong>GCS IP:</strong> {drone.gcs_ip}</p>
                        <p><strong>Initial Launch Position:</strong> ({drone.x}, {drone.y})</p>
                        <p><strong>Position ID:</strong> {drone.pos_id}</p>
        
                        <div>
                        <button className="edit" onClick={() => startEditing(drone.hw_id)}>Edit</button>
<button className="remove" onClick={() => removeDrone(drone.hw_id)}>Remove</button>

                        </div>
                    </>
                )}
            </div>
        ));
        

        
        const startEditing = (hw_id) => {
            setEditingDroneId(hw_id);
            setTimeout(() => { // Set a timeout to allow React to rerender with the updated state
                document.querySelector(`.drone-config-card[data-hw-id="${hw_id}"]`).scrollIntoView({ behavior: "smooth" });
            }, 0);
        };
        

        const saveChanges = (hw_id, updatedData) => {
            const { hw_id: newHwId } = updatedData;
            if (configData.some(d => d.hw_id === newHwId && d.hw_id !== hw_id)) {
                alert("The selected hardware ID is already in use. Please choose another one.");
                return;
            }
            setConfigData(prevConfig => {
                return prevConfig.map(drone => drone.hw_id === hw_id ? updatedData : drone);
            });
            // Stop editing after saving
            setEditingDroneId(null);
        };
        
        

        const addNewDrone = () => {
            // Generate new hw_id (one increment more than the current maximum)
            const newHwId = availableHwIds[0].toString();
        
            const newDrone = {
                hw_id: newHwId.toString(),
                ip: "", // you can set default values here if needed
                mavlink_port: "",
                debug_port: "",
                gcs_ip: configData.length > 0 ? configData[0].gcs_ip : "",
                x: "0",
                y: "0",
                pos_id: newHwId.toString()

            };
        
            // Add the new drone to configData state
            setConfigData(prevConfig => [...prevConfig, newDrone]);
        };

        const removeDrone = (hw_id) => {
            
            if (window.confirm(`Are you sure you want to remove Drone ${hw_id}?`)) {
                setConfigData(prevConfig => prevConfig.filter(drone => drone.hw_id !== hw_id));
            }
                    };
        
        const handleSaveChangesToServer = () => {
            const maxId = Math.max(...configData.map(drone => parseInt(drone.hw_id)));
for (let i = 1; i <= maxId; i++) {
    if (!configData.some(drone => parseInt(drone.hw_id) === i)) {
        alert(`Missing Drone ID: ${i}. Please create the missing drone before saving.`);
        return;
    }
}

            axios.post('http://localhost:5000/save-config-data', configData)
                .then(response => {
                    alert(response.data.message);
                })
                .catch(error => {
                    console.error("Error saving updated config data:", error);
                    if (error.response && error.response.data.message) {
                        alert(error.response.data.message);
                    } else {
                        alert('Error saving data.');
                    }
                });
        };
        

        const handleRevertChanges = () => {
            if (window.confirm("Are you sure you want to reload and lose all current settings?")) {
                // Fetch the original config data
                axios.get('http://localhost:5000/get-config-data')
                    .then(response => {
                        setConfigData(response.data);
                    })
                    .catch(error => {
                        console.error("Error fetching original config data:", error);
                    });
            }
        };
        
        
        return (
            <div className="mission-config-container">
    <h2>Mission Configuration</h2>
    <button onClick={addNewDrone}>Add New Drone</button>

    <div className="content-flex">
        <div className="drone-cards">
            {droneCards}
        </div>
        
        <div className="initial-launch-plot">
            <InitialLaunchPlot drones={configData} onDroneClick={startEditing} />
        </div>
    </div>

    <div className="control-buttons">
        <button className="save" onClick={handleSaveChangesToServer}>Save Changes</button>
        <button className="revert" onClick={handleRevertChanges}>Revert</button>
    </div>
</div>

        );
    }

    export default MissionConfig;
