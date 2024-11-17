//app/dashboard/drone-dashboard/src/utilities/flightModeUtils.js
import { FLIGHT_MODES } from '../constants/flightModes';

export const getFlightModeTitle = (code) => {
    return FLIGHT_MODES[code] || code;
};