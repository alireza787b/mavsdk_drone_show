import React, { useState } from 'react';
import Overview from './components/Overview';
import DroneDetail from './components/DroneDetail';

const App = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);

// Function to go back to the overview
const goBack = () => {
  setSelectedDrone(null);
};

return (
  <div>
    {selectedDrone ? (
      <DroneDetail drone={selectedDrone} goBack={goBack} /> // Pass the goBack function
    ) : (
      <Overview setSelectedDrone={setSelectedDrone} />
    )}
  </div>
);
};

export default App;
