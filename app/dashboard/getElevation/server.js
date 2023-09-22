const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
const PORT = 5001;

// Use the CORS middleware to handle CORS issues
app.use(cors());

// In-memory cache to store elevation data
const elevationCache = {};

app.get('/elevation', async (req, res) => {
    const lat = req.query.lat;
    const lon = req.query.lon;
    
    // Validate latitude and longitude
    if(lat == null || lon == null) {
        console.error('Error: Latitude and Longitude must be provided'); // Log error details to the server terminal
        return res.status(400).send('Latitude and Longitude must be provided');
    }

    const coordKey = `${lat},${lon}`; // Create a unique key for each set of coordinates

    // Check if the elevation data for the requested coordinates is already in the cache
    if (elevationCache[coordKey]) {
        console.log(`Cache hit for coordinates ${coordKey}`); // Log cache hit to the server terminal
        return res.json(elevationCache[coordKey]);
    }

    try {
        console.log(`Fetching elevation data online for coordinates ${coordKey}`); // Log online fetch to the server terminal
        const response = await axios.get(`https://api.opentopodata.org/v1/srtm90m?locations=${lat},${lon}`);
        // Store the received elevation data in the cache
        elevationCache[coordKey] = response.data;
        res.json(response.data);
    } catch (error) {
        console.error(`Error fetching elevation for coordinates ${coordKey}:`, error); // Log error details to the server terminal
        res.status(500).send("Error fetching elevation");
    }
});
