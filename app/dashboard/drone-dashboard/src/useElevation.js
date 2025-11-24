import { useState, useEffect } from 'react';
import { getElevation } from './utilities/utilities'; // Make sure to correct the import path if needed

const useElevation = (lat, lon) => {
  const [elevation, setElevation] = useState(null);

  useEffect(() => {
    // Skip API call if coordinates are null, undefined, or invalid
    if (lat === null || lat === undefined || lon === null || lon === undefined) {
      setElevation(null);
      return;
    }

    const fetchData = async () => {
      const fetchedElevation = await getElevation(lat, lon);
      setElevation(fetchedElevation);
    };

    fetchData();
  }, [lat, lon]);

  return elevation;
};

export default useElevation;
