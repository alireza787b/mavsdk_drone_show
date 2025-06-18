// src/components/trajectory/SearchBar.js
import React, { useState, useRef, useEffect } from 'react';
import { FaSearch, FaMapMarkerAlt, FaTimes, FaSpinner } from 'react-icons/fa';
import '../../styles/SearchBar.css';

const SearchBar = ({ onLocationSelect }) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [error, setError] = useState('');
  const searchRef = useRef(null);

  // Close suggestions when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowSuggestions(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSearch = async (e) => {
    e.preventDefault();
    performSearch(searchQuery);
  };

  const performSearch = async (query) => {
    if (!query.trim()) return;

    setError('');
    
    // Check if it's coordinates (lat,lon or lat, lon format)
    const coordsMatch = query.match(/^(-?\d+\.?\d*),?\s*(-?\d+\.?\d*)$/);
    if (coordsMatch) {
      const lat = parseFloat(coordsMatch[1]);
      const lon = parseFloat(coordsMatch[2]);
      
      if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
        onLocationSelect(lon, lat, 5000);
        setSearchQuery(`${lat.toFixed(6)}, ${lon.toFixed(6)}`);
        setShowSuggestions(false);
        return;
      } else {
        setError('Invalid coordinates. Latitude must be between -90 and 90, longitude between -180 and 180.');
        return;
      }
    }

    // Otherwise, use Google Geocoding API
    setIsSearching(true);
    try {
      const response = await fetch(
        `https://maps.googleapis.com/maps/api/geocode/json?address=${encodeURIComponent(
          query
        )}&key=${process.env.REACT_APP_GOOGLE_MAPS_API_KEY}`
      );
      
      const data = await response.json();
      
      if (data.status === 'OK' && data.results && data.results.length > 0) {
        // Show suggestions if multiple results
        if (data.results.length > 1) {
          setSuggestions(data.results.slice(0, 5)); // Show max 5 suggestions
          setShowSuggestions(true);
        } else {
          // Single result - go directly
          const location = data.results[0].geometry.location;
          onLocationSelect(location.lng, location.lat, 5000);
          setSearchQuery(data.results[0].formatted_address);
          setShowSuggestions(false);
        }
      } else if (data.status === 'ZERO_RESULTS') {
        setError('Location not found. Try a different search term.');
      } else {
        setError('Search failed. Please check your API key.');
      }
    } catch (error) {
      console.error('Search error:', error);
      setError('Network error. Please check your connection.');
    } finally {
      setIsSearching(false);
    }
  };

  const selectSuggestion = (suggestion) => {
    const location = suggestion.geometry.location;
    onLocationSelect(location.lng, location.lat, 5000);
    setSearchQuery(suggestion.formatted_address);
    setShowSuggestions(false);
    setSuggestions([]);
  };

  const clearSearch = () => {
    setSearchQuery('');
    setSuggestions([]);
    setShowSuggestions(false);
    setError('');
  };

  return (
    <div className="search-bar-container" ref={searchRef}>
      <form className="search-bar" onSubmit={handleSearch}>
        <div className="search-input-wrapper">
          <FaMapMarkerAlt className="search-icon location" />
          <input
            type="text"
            className={`search-input ${error ? 'error' : ''}`}
            placeholder="Search location or enter coordinates (lat, lon)"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              setError('');
            }}
            disabled={isSearching}
          />
          {searchQuery && (
            <button
              type="button"
              className="clear-button"
              onClick={clearSearch}
              disabled={isSearching}
            >
              <FaTimes />
            </button>
          )}
          <button
            type="submit"
            className="search-button"
            disabled={isSearching || !searchQuery.trim()}
          >
            {isSearching ? <FaSpinner className="spinner" /> : <FaSearch />}
          </button>
        </div>
        {error && <div className="search-error">{error}</div>}
      </form>

      {showSuggestions && suggestions.length > 0 && (
        <div className="search-suggestions">
          {suggestions.map((suggestion, index) => (
            <div
              key={index}
              className="suggestion-item"
              onClick={() => selectSuggestion(suggestion)}
            >
              <FaMapMarkerAlt className="suggestion-icon" />
              <div className="suggestion-text">
                <div className="suggestion-main">
                  {suggestion.address_components[0].long_name}
                </div>
                <div className="suggestion-sub">
                  {suggestion.formatted_address}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default SearchBar;
