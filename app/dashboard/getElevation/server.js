const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
const PORT = 5001;

app.use(cors());

const elevationCache = {};
const RADIUS = 20 / 1000; // 20 meters in kilometers

// Function to calculate distance between two geographical points
function getDistance(lat1, lon1, lat2, lon2) {
    const R = 6371; // Radius of the Earth in kilometers
    const dLat = (lat2 - lat1) * (Math.PI / 180);
    const dLon = (lon2 - lon1) * (Math.PI / 180);
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * (Math.PI / 180)) * Math.cos(lat2 * (Math.PI / 180)) *
              Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c; // Distance in kilometers
}

app.get('/elevation', async (req, res) => {
    const lat = parseFloat(req.query.lat);
    const lon = parseFloat(req.query.lon);

    if(isNaN(lat) || isNaN(lon)) {
        console.error('Error: Valid Latitude and Longitude must be provided');
        return res.status(400).send('Valid Latitude and Longitude must be provided');
    }

    // Check each cached coordinate
    for(const coordKey in elevationCache) {
        const [cachedLat, cachedLon] = coordKey.split(',').map(Number);
        const distance = getDistance(lat, lon, cachedLat, cachedLon);
        if(distance < RADIUS) {
            console.log(`Cache hit for coordinates ${coordKey}`);
            return res.json(elevationCache[coordKey]);
        }
    }

    try {
        console.log(`Fetching elevation data online for coordinates ${lat},${lon}`);
        const response = await axios.get(`https://api.opentopodata.org/v1/srtm90m?locations=${lat},${lon}`);
        elevationCache[`${lat},${lon}`] = response.data;
        res.json(response.data);
    } catch (error) {
        console.error(`Error fetching elevation for coordinates ${lat},${lon}:`, error);
        res.status(500).send("Error fetching elevation");
    }
});

app.listen(PORT, () => {
    console.log(`Server started on http://localhost:${PORT}`);
});
