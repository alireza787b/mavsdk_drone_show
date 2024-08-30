import React, { useEffect, useState } from 'react';
import '../styles/MissionDetails.css';
import { getCustomShowImageURL, getBackendURL } from '../utilities/utilities'; // Import utility functions

const MissionDetails = ({
  missionType,
  icon,
  label,
  description,
  useSlider,
  timeDelay,
  selectedTime,
  onTimeDelayChange,
  onTimePickerChange,
  onSliderToggle,
  onSend,
  onBack,
}) => {
  const [customShowImageSrc, setCustomShowImageSrc] = useState(null);
  const [droneShowPlotSrc, setDroneShowPlotSrc] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    // Fetch the custom show image if the mission type is CUSTOM_CSV_DRONE_SHOW
    if (missionType === 'CUSTOM_CSV_DRONE_SHOW') {
      async function fetchCustomShowImage() {
        try {
          const response = await fetch(getCustomShowImageURL());
          if (response.ok) {
            const imageBlob = await response.blob();
            const imageObjectURL = URL.createObjectURL(imageBlob);
            setCustomShowImageSrc(imageObjectURL);
          } else {
            setErrorMessage('Failed to load custom show image.');
          }
        } catch (error) {
          setErrorMessage('An error occurred while loading the custom show image.');
        }
      }
      fetchCustomShowImage();
    }

    // Fetch the drone show plot image for all drone missions
    async function fetchDroneShowPlot() {
      try {
        const plotUrl = `${getBackendURL()}/get-show-plots/all_drones.png`;
        setDroneShowPlotSrc(plotUrl);
      } catch (error) {
        setErrorMessage('An error occurred while loading the drone show plot image.');
      }
    }
    fetchDroneShowPlot();
  }, [missionType]);

  return (
    <div className="mission-details">
      <div className="selected-mission-card">
        <div className="mission-icon">{icon}</div>
        <div className="mission-name">{label}</div>
        <div className="mission-description">{description}</div>
      </div>

      {/* Display custom show image if it's the selected mission */}
      {customShowImageSrc && (
        <div className="custom-show-preview">
          <h3>Custom Show Preview:</h3>
          <img src={customShowImageSrc} alt="Custom Drone Show" className="custom-show-image" />
        </div>
      )}

      {/* Display drone show plot image for all missions */}
      {droneShowPlotSrc && (
        <div className="drone-show-preview">
          <h3>Drone Show Plot Preview:</h3>
          <img src={droneShowPlotSrc} alt="Drone Show Plot" className="drone-show-image" />
        </div>
      )}

      <div className="time-selection">
        <label>
          <input
            type="radio"
            checked={useSlider}
            onChange={() => onSliderToggle(true)}
          />
          Set delay in seconds
        </label>
        <label>
          <input
            type="radio"
            checked={!useSlider}
            onChange={() => onSliderToggle(false)}
          />
          Set exact time
        </label>
      </div>

      {useSlider ? (
        <div className="time-delay-slider">
          <label htmlFor="time-delay">Time Delay (seconds): {timeDelay}</label>
          <input
            type="range"
            id="time-delay"
            min="0"
            max="60"
            value={timeDelay}
            onChange={(e) => onTimeDelayChange(e.target.value)}
          />
        </div>
      ) : (
        <div className="time-picker">
          <label htmlFor="time-picker">Select Time:</label>
          <input
            type="time"
            id="time-picker"
            value={selectedTime}
            onChange={(e) => onTimePickerChange(e.target.value)}
            step="1"
          />
        </div>
      )}

      <button onClick={onSend} className="mission-button">
        Send Command
      </button>
      <button onClick={onBack} className="back-button">
        Back
      </button>
    </div>
  );
};

export default MissionDetails;
