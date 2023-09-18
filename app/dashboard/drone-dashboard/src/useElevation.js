import { useState, useEffect } from 'react';
import { getElevation } from './utilities'; // Make sure to correct the import path if needed

const useElevation = (lat, lon) => {
  const [elevation, setElevation] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      const fetchedElevation = await getElevation(lat, lon);
      setElevation(fetchedElevation);
    };

    fetchData();
  }, [lat, lon]);

  return elevation;
};

export default useElevation;
