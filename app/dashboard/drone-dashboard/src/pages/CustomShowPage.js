import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import '../styles/CustomShowPage.css';
import { getCustomShowImageURL } from '../utilities/utilities';
import useFetch from '../hooks/useFetch';

const CustomShowPage = () => {
    const [imageLoadFailed, setImageLoadFailed] = useState(false);
    const { data: customShowInfo } = useFetch('/get-custom-show-info');
    const previewAvailable = Boolean(customShowInfo?.preview_exists);
    const imageSrc = useMemo(
        () => (previewAvailable ? getCustomShowImageURL() : null),
        [previewAvailable],
    );

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
            <p className="description">
                If you want the normal operator workflow with ZIP import, preview, and per-drone trajectory processing,
                use <Link to="/drone-show-design">Show Design</Link> instead.
            </p>
            {customShowInfo?.exists && (
                <p className="description">
                    Active file: <code>{customShowInfo.filename}</code> • duration {customShowInfo.duration_sec}s • max altitude {customShowInfo.max_altitude}m
                </p>
            )}
            {!customShowInfo?.exists && (
                <div className="error-message">
                    No active custom CSV is loaded yet. Place <code>active.csv</code> in <code>shapes_sitl/</code>
                    for SITL or <code>shapes/</code> for real hardware, then refresh this page.
                </div>
            )}
            {customShowInfo?.exists && !previewAvailable && (
                <div className="error-message">
                    No preview image has been generated for the active custom CSV yet. The mission can still be valid,
                    but operators will not get a visual cross-check until the preview is regenerated.
                </div>
            )}
            {previewAvailable && imageLoadFailed && (
                <div className="error-message">
                    The backend reports a preview image exists, but the browser could not display it. Refresh once, and
                    if it persists regenerate the custom trajectory preview on the server.
                </div>
            )}
            {imageSrc && !imageLoadFailed ? (
                <img
                    src={imageSrc}
                    alt="Custom Drone Show"
                    className="custom-show-image"
                    onError={() => setImageLoadFailed(true)}
                    onLoad={() => setImageLoadFailed(false)}
                />
            ) : (
                customShowInfo?.exists && !previewAvailable && (
                    <p>Custom preview image not available yet. Generate the preview if operators need a visual check.</p>
                )
            )}
        </div>
    );
};

export default CustomShowPage;
