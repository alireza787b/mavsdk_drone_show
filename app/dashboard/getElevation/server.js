const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
const PORT = 5001;

app.use(cors());

const elevationCache = {};

app.get('/elevation', async (req, res) => {
    const lat = req.query.lat;
    const lon = req.query.lon;

    if(lat == null || lat === 'null' || lon == null || lon === 'null') {
        console.error('Error: Latitude and Longitude must be provided');
        return res.status(400).send('Latitude and Longitude must be provided');
    }


    const coordKey = `${lat},${lon}`;

    if (elevationCache[coordKey]) {
        console.log(`Cache hit for coordinates ${coordKey}`);
        return res.json(elevationCache[coordKey]);
    }

    try {
        console.log(`Fetching elevation data online for coordinates ${coordKey}`);
        const response = await axios.get(`https://api.opentopodata.org/v1/srtm90m?locations=${lat},${lon}`);
        elevationCache[coordKey] = response.data;
        res.json(response.data);
    } catch (error) {
        console.error(`Error fetching elevation for coordinates ${coordKey}:`, error);
        res.status(500).send("Error fetching elevation");
    }
});

app.listen(PORT, () => {
    console.log(`Server started on http://localhost:${PORT}`);
});
