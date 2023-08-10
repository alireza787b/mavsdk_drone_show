import React from 'react';

const DroneDetail = ({ drone, goBack }) => {
    return (
      <div>
        <button onClick={goBack}>Return to Overview</button> {/* Button to go back */}
        <h1>Drone Detail for HW_ID: {drone.hw_ID}</h1>
        <p>Last Updated: {drone.lastUpdated}</p>
        <p>Mission: {drone.Mission}</p>
        <p>State: {drone.State}</p>
        <p>Altitude: {drone.Position_Alt}</p>
        <p>Latitude: {drone.Position_Lat}</p>
        <p>Longitude: {drone.Position_Long}</p>
        <p>Velocity North: {drone.Velocity_North}</p>
        <p>Velocity East: {drone.Velocity_East}</p>
        <p>Velocity Down: {drone.Velocity_Down}</p>
        <p>Yaw: {drone.Yaw}</p>
        <p>Battery Voltage: {drone.Battery_Voltage}</p>
        <p>Follow Mode: {drone.Follow_Mode}</p>
        {/* Add more details as needed */}
      </div>
    );
  };
  

export default DroneDetail;
