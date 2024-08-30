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
            <p className="description">
                This custom drone show is based on the <code>shape/active.csv</code> file. You can create various shapes using the 
                <code>csvcreator.py</code> script included in the source code, such as an eight shape, spiral, heart shape, zigzag, 
                or you can use a custom CSV template. Each drone executes its portion of the CSV independently based on its home 
                position, unlike the Skybrush-based drone show controlled via the Show Design page.
            </p>
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
