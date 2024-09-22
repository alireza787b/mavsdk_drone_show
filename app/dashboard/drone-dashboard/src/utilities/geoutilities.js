// src/utilities/geoutilities.js

import LatLon from 'geodesy/latlon-spherical.js';

/**
 * Converts relative north-east (x, y) coordinates to absolute latitude and longitude.
 * 
 * @param {string} originLat - Origin latitude in decimal degrees.
 * @param {string} originLon - Origin longitude in decimal degrees.
 * @param {number} x - Distance north in meters.
 * @param {number} y - Distance east in meters.
 * @returns {Object} An object containing the converted latitude and longitude.
 */
export const convertToLatLon = (originLat, originLon, x, y) => {
    try {
        const origin = new LatLon(parseFloat(originLat), parseFloat(originLon));

        // Calculate the distance and bearing from the origin
        const distance = Math.sqrt(x ** 2 + y ** 2); // in meters
        const bearing = (Math.atan2(y, x) * 180) / Math.PI; // Convert radians to degrees

        // Calculate the destination point
        const destination = origin.destinationPoint(distance, bearing);

        return {
            latitude: destination.lat,
            longitude: destination.lon,
        };
    } catch (error) {
        console.error("Error converting coordinates:", error);
        return {
            latitude: originLat,
            longitude: originLon,
        };
    }
};