import React, { useState, useEffect } from 'react';
import '../styles/CustomShowPage.css';
import { getCustomShowImageURL } from '../utilities/utilities';  // Import the new utility function

const CustomShowPage = () => {
    const [imageSrc, setImageSrc] = useState(null);
    const [errorMessage, setErrorMessage] = useState('');

    useEffect(() => {
        // Fetch the custom show image from the server
        async function fetchCustomShowImage() {
            try {
                const response = await fetch(getCustomShowImageURL());  // Use the utility function to get the correct URL
                if (response.ok) {
                    const imageBlob = await response.blob();
                    const imageObjectURL = URL.createObjectURL(imageBlob);
                    setImageSrc(imageObjectURL);
                } else {
                    setErrorMessage('Failed to load custom show image.');
                }
            } catch (error) {
                setErrorMessage('An error occurred while loading the custom show image.');
            }
        }

        fetchCustomShowImage();
    }, []);

    return (
        <div className="custom-show-container">
            <h1>Custom Drone Show</h1>
            {errorMessage && <div className="error-message">{errorMessage}</div>}
            {imageSrc ? (
                <img src={imageSrc} alt="Custom Drone Show" className="custom-show-image" />
            ) : (
                !errorMessage && <p>Loading custom show image...</p>
            )}
        </div>
    );
};

export default CustomShowPage;
