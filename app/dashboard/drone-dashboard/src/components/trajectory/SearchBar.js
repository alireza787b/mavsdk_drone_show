//app/dashboard/drone-dashboard/src/components/trajectory/SearchBar.js
import React, { useState } from 'react';
import PropTypes from 'prop-types';

const SearchBar = ({ onLocationSelect }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const handleSearch = async () => {
    if (!searchTerm.trim()) return;
    
    setIsLoading(true);
    try {
      const coordMatch = searchTerm.match(/^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$/);
      if (coordMatch) {
        const lat = parseFloat(coordMatch[1]);
        const lon = parseFloat(coordMatch[2]);
        onLocationSelect(lon, lat, 1000);
        return;
      }
      
      console.log('Searching for:', searchTerm);
      alert('Please enter coordinates in format: "latitude, longitude" (e.g., "37.7749, -122.4194")');
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  return (
    <div className="search-bar">
      <input
        type="text"
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder="Search location or enter coordinates (lat, lon)"
        disabled={isLoading}
      />
      <button onClick={handleSearch} disabled={isLoading || !searchTerm.trim()}>
        {isLoading ? '🔍' : '🔎'}
      </button>
    </div>
  );
};

SearchBar.propTypes = {
  onLocationSelect: PropTypes.func.isRequired,
};

export default SearchBar;
