import React, { useState, useEffect } from 'react';
import '../styles/CustomShowPage.css';

const CustomShowPage = () => {
    const [imageSrc, setImageSrc] = useState(null);
    const [errorMessage, setErrorMessage] = useState('');

    useEffect(() => {
        // Fetch the custom show image from the server
        async function fetchCustomShowImage() {
            try {
                const response = await fetch('/get-custom-show-image');
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
        <div className="custom-show-page">
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
