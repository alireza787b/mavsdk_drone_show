import React, { useState, useEffect } from 'react';
import '../styles/CustomShowPage.css';
import { getCustomShowImageURL } from '../utilities/utilities';
import useFetch from '../hooks/useFetch';

const CustomShowPage = () => {
    const [imageSrc, setImageSrc] = useState(null);
    const [errorMessage, setErrorMessage] = useState('');
    const { data: customShowInfo } = useFetch('/get-custom-show-info');

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
                This page is the preview surface for the advanced custom CSV mode. It uses the shared
                <code> shapes/active.csv </code> or <code> shapes_sitl/active.csv </code> workflow rather than the
                normal SkyBrush ZIP import used on the Show Design page.
            </p>
            <p className="description">
                In this mode, each drone runs the same authored CSV relative to its own launch frame. That is useful
                for specialized testing and research, but it is a different operator workflow from the normal
                multi-drone SkyBrush show pipeline. Treat it as an advanced/manual mode.
            </p>
            {customShowInfo?.exists && (
                <p className="description">
                    Active file: <code>{customShowInfo.filename}</code> • duration {customShowInfo.duration_sec}s • max altitude {customShowInfo.max_altitude}m
                </p>
            )}
            {errorMessage && <div className="error-message">{errorMessage}</div>}
            {imageSrc ? (
                <img src={imageSrc} alt="Custom Drone Show" className="custom-show-image" />
            ) : (
                !errorMessage && <p>Custom preview image not available yet. Generate or upload the active CSV first.</p>
            )}
        </div>
    );
};

export default CustomShowPage;
