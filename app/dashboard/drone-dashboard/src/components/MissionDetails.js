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
  const [imageSrc, setImageSrc] = useState(null);
  const [errorMessage, setErrorMessage] = useState('');

  useEffect(() => {
    // Reset the image and error state when the mission type changes
    setImageSrc(null);
    setErrorMessage('');

    // Fetch the appropriate image based on the mission type
    async function fetchImage() {
      try {
        let imageURL = '';

        if (missionType === 'CUSTOM_CSV_DRONE_SHOW') {
          imageURL = getCustomShowImageURL();
        } else if (missionType === 'DRONE_SHOW_FROM_CSV') {
          imageURL = `${getBackendURL()}/get-show-plots/all_drones.png`;
        } else {
          return; // If no image is relevant for the mission type, exit the function
        }

        const response = await fetch(imageURL);
        if (response.ok) {
          const imageBlob = await response.blob();
          const imageObjectURL = URL.createObjectURL(imageBlob);
          setImageSrc(imageObjectURL);
        } else {
          setErrorMessage('Failed to load the image.');
        }
      } catch (error) {
        setErrorMessage('An error occurred while loading the image.');
      }
    }

    fetchImage();
  }, [missionType]);

  return (
    <div className="mission-details">
      <div className="selected-mission-card">
        <div className="mission-icon">{icon}</div>
        <div className="mission-name">{label}</div>
        <div className="mission-description">{description}</div>
      </div>

      {/* Display the image only if it exists */}
      {imageSrc && (
        <div className="image-preview">
          <h3>Show Preview:</h3>
          <img src={imageSrc} alt="Drone Show" className="show-image" />
        </div>
      )}

      {errorMessage && <div className="error-message">{errorMessage}</div>}

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
