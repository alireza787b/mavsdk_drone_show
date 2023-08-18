import React, { useState, useEffect } from 'react';
import '../styles/DroneCard.css';

const categorizeDroneRole = (drone, followerCounts, topLeaderIdsSet) => {
    if (drone.follow === '0') return 'Top Leader';
    if (!topLeaderIdsSet.has(drone.hw_id) && followerCounts[drone.hw_id]) return 'Intermediate Leader';
    return 'Follower';
};
const dronesFollowing = (droneId, allDrones) => {
    return allDrones.filter(d => d.follow === droneId).map(d => d.hw_id);
};

const DroneCard = ({ drone, allDrones, onSaveChanges, isSelected }) => {
    console.log("Rendering DroneCard for Drone ID:", drone.hw_id, "isSelected:", isSelected);

    const [isExpanded, setIsExpanded] = useState(false);
    const [selectedFollow, setSelectedFollow] = useState(drone.follow);
    const [offsets, setOffsets] = useState({
        n: drone.offset_n,
        e: drone.offset_e,
        alt: drone.offset_alt
    });

    // Count followers for each drone
    const followerCounts = {};
    allDrones.forEach(d => {
        if (!followerCounts[d.follow]) {
            followerCounts[d.follow] = 0;
        }
        followerCounts[d.follow]++;
    });

    const topLeaderIdsSet = new Set(allDrones.filter(d => d.follow === '0').map(leader => leader.hw_id));
    const role = categorizeDroneRole(drone, followerCounts, topLeaderIdsSet);

    useEffect(() => {
        if (selectedFollow === '0') {
            setOffsets({ n: 0, e: 0, alt: 0 });
        }
    }, [selectedFollow]);

    const handleSave = () => {
        onSaveChanges(drone.hw_id, {
            ...drone,
            follow: selectedFollow,
            offset_n: offsets.n,
            offset_e: offsets.e,
            offset_alt: offsets.alt
        });
        setIsExpanded(false);
    };

    const dronesThatFollowThis = dronesFollowing(drone.hw_id, allDrones);

    return (
<div className={`drone-card ${isExpanded ? 'selected-drone' : ''} ${isSelected ? 'selected' : ''}`}  >
            <h3 onClick={() => setIsExpanded(!isExpanded)}>Drone ID: {drone.hw_id}</h3>
            
            <p>
                {role === 'Top Leader' ? 
                    <span className="role leader">Top Leader</span> : 
                    role === 'Intermediate Leader' ? 
                    <span className="role intermediate">Intermediate Leader (Follows Drone {selectedFollow})</span> :
                    <span className="role follower">Follows Drone {selectedFollow}</span>
                }
            </p>
            
            {dronesThatFollowThis.length > 0 && (
                <p className="followed-by-text">
                    Followed By: {dronesThatFollowThis.join(', ')}
                </p>
            )}

            <p className="collapsible-details">
                Position Offset (m): North: {drone.offset_n}, East: {drone.offset_e}, Altitude: {drone.offset_alt}
            </p>
           
            {isExpanded && (
    <div>
        <div className="form-group">
            <label>Role: </label>
            <select value={selectedFollow} onChange={e => setSelectedFollow(e.target.value)}>
                <option value="0">Top Leader</option>
                {allDrones.map(d => {
                    if (d.hw_id !== drone.hw_id) {
                        return <option key={d.hw_id} value={d.hw_id}> Follow Drone {d.hw_id}</option>;
                    } else {
                        return null;
                    }
                })}
            </select>
        </div>

        <div className="form-group">
            <label>Offset N (m): </label>
            <input 
                type="number" 
                value={offsets.n} 
                onChange={e => setOffsets(prev => ({ ...prev, n: e.target.value }))}
                disabled={selectedFollow === '0'}
            />
        </div>

        <div className="form-group">
            <label>Offset E (m): </label>
            <input 
                type="number" 
                value={offsets.e} 
                onChange={e => setOffsets(prev => ({ ...prev, e: e.target.value }))}
                disabled={selectedFollow === '0'}
            />
        </div>

        <div className="form-group">
            <label>Offset Altitude (m): </label>
            <input 
                type="number" 
                value={offsets.alt} 
                onChange={e => setOffsets(prev => ({ ...prev, alt: e.target.value }))}
                disabled={selectedFollow === '0'}
            />
        </div>

        <button onClick={handleSave}>Save Changes</button>
    </div>
)}
        </div>
    );
};

export default DroneCard;
