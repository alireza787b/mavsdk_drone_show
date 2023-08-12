const express = require('express');
const axios = require('axios');
const cors = require('cors');

const app = express();
const PORT = 5001;

// Use the CORS middleware to handle CORS issues
app.use(cors());

app.get('/elevation', async (req, res) => {
    const lat = req.query.lat;
    const lon = req.query.lon;

    try {
        const response = await axios.get(`https://api.opentopodata.org/v1/srtm90m?locations=${lat},${lon}`);
        res.json(response.data);
    } catch (error) {
        console.error("Error fetching elevation:", error);
        res.status(500).send("Error fetching elevation");
    }
});

app.listen(PORT, () => {
    console.log(`Server started on http://localhost:${PORT}`);
});
