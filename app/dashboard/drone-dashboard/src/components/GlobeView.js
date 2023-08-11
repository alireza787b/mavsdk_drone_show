import React, { useRef, useEffect } from 'react';
import { Viewer } from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';


const GlobeView = () => {
    const cesiumContainer = useRef(null); // This ref will be attached to a DOM element

    useEffect(() => {
        if (cesiumContainer.current) {
            const viewer = new Viewer(cesiumContainer.current);
            
            // Additional Cesium setup and customization can be done here.
        }
    }, []);

    return (
        <div ref={cesiumContainer} style={{ width: '100%', height: '600px' }}>
            {/* Cesium renders inside this container */}
        </div>
    );
}


export default GlobeView;
