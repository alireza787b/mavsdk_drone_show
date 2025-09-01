// src/components/trajectory/SearchBar.js
// PHASE 2 ENHANCEMENTS: Real geocoding search with location suggestions

import React, { useState, useEffect, useRef, useCallback } from 'react';
import PropTypes from 'prop-types';

const SearchBar = ({ onLocationSelect }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [error, setError] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(-1);
  
  const searchInputRef = useRef(null);
  const suggestionsRef = useRef(null);
  const debounceRef = useRef(null);

  // PHASE 2: Enhanced geocoding with multiple providers
  const geocodeLocation = async (query) => {
    try {
      setError('');
      
      // Try coordinate parsing first (lat, lon format)
      const coordMatch = query.match(/^(-?\d+\.?\d*),\s*(-?\d+\.?\d*)$/);
      if (coordMatch) {
        const lat = parseFloat(coordMatch[1]);
        const lon = parseFloat(coordMatch[2]);
        
        if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
          return [{
            name: `Coordinates: ${lat.toFixed(6)}, ${lon.toFixed(6)}`,
            latitude: lat,
            longitude: lon,
            type: 'coordinate',
            description: 'Manual coordinates'
          }];
        }
      }

      // Try Nominatim (OpenStreetMap) geocoding
      const nominatimUrl = `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=5&addressdetails=1`;
      
      const response = await fetch(nominatimUrl, {
        headers: {
          'User-Agent': 'Drone-Trajectory-Planning/1.0'
        }
      });

      if (!response.ok) {
        throw new Error('Geocoding service unavailable');
      }

      const data = await response.json();
      
      return data.map(item => ({
        name: item.display_name.split(',').slice(0, 3).join(', '),
        fullName: item.display_name,
        latitude: parseFloat(item.lat),
        longitude: parseFloat(item.lon),
        type: item.type || 'location',
        description: item.class || 'Location',
        boundingBox: item.boundingbox
      }));

    } catch (error) {
      console.warn('Geocoding error:', error);
      
      // Fallback to coordinate parsing with error handling
      const coordFallback = query.match(/(-?\d+\.?\d+)[\s,]+(-?\d+\.?\d+)/);
      if (coordFallback) {
        const lat = parseFloat(coordFallback[1]);
        const lon = parseFloat(coordFallback[2]);
        
        if (!isNaN(lat) && !isNaN(lon)) {
          return [{
            name: `Coordinates: ${lat.toFixed(6)}, ${lon.toFixed(6)}`,
            latitude: lat,
            longitude: lon,
            type: 'coordinate',
            description: 'Parsed coordinates'
          }];
        }
      }
      
      throw new Error('Could not find location. Try entering coordinates as "latitude, longitude"');
    }
  };

  // PHASE 2: Debounced search for better UX
  const debouncedSearch = useCallback((query) => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current);
    }

    debounceRef.current = setTimeout(async () => {
      if (query.length < 2) {
        setSuggestions([]);
        setShowSuggestions(false);
        return;
      }

      setIsLoading(true);
      try {
        const results = await geocodeLocation(query);
        setSuggestions(results);
        setShowSuggestions(results.length > 0);
        setSelectedIndex(-1);
      } catch (err) {
        setError(err.message);
        setSuggestions([]);
        setShowSuggestions(false);
      } finally {
        setIsLoading(false);
      }
    }, 300);
  }, []);

  // Handle input changes
  const handleInputChange = (e) => {
    const value = e.target.value;
    setSearchTerm(value);
    setError('');
    
    if (value.trim()) {
      debouncedSearch(value.trim());
    } else {
      setSuggestions([]);
      setShowSuggestions(false);
    }
  };

  // Handle suggestion selection
  const handleSuggestionSelect = (suggestion) => {
    setSearchTerm(suggestion.name);
    setShowSuggestions(false);
    setSuggestions([]);
    setSelectedIndex(-1);
    
    // Default altitude for search results (can be edited later)
    const defaultAltitude = 100; // MSL meters
    onLocationSelect(suggestion.longitude, suggestion.latitude, defaultAltitude);
  };

  // Handle direct search (Enter key or search button)
  const handleSearch = async () => {
    if (!searchTerm.trim()) return;
    
    setIsLoading(true);
    setShowSuggestions(false);
    
    try {
      const results = await geocodeLocation(searchTerm.trim());
      if (results.length > 0) {
        const defaultAltitude = 100; // MSL meters
        onLocationSelect(results[0].longitude, results[0].latitude, defaultAltitude);
      } else {
        setError('No locations found. Try entering coordinates as "latitude, longitude"');
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // Handle keyboard navigation
  const handleKeyDown = (e) => {
    if (!showSuggestions) {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleSearch();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev < suggestions.length - 1 ? prev + 1 : 0
        );
        break;
      
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex(prev => 
          prev > 0 ? prev - 1 : suggestions.length - 1
        );
        break;
      
      case 'Enter':
        e.preventDefault();
        if (selectedIndex >= 0 && suggestions[selectedIndex]) {
          handleSuggestionSelect(suggestions[selectedIndex]);
        } else {
          handleSearch();
        }
        break;
      
      case 'Escape':
        setShowSuggestions(false);
        setSelectedIndex(-1);
        searchInputRef.current?.blur();
        break;
    }
  };

  // Handle click outside to close suggestions
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (suggestionsRef.current && !suggestionsRef.current.contains(event.target)) {
        setShowSuggestions(false);
        setSelectedIndex(-1);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Clear search
  const handleClear = () => {
    setSearchTerm('');
    setSuggestions([]);
    setShowSuggestions(false);
    setError('');
    setSelectedIndex(-1);
    searchInputRef.current?.focus();
  };

  // Get location type icon
  const getLocationIcon = (type) => {
    switch (type) {
      case 'coordinate': return '🎯';
      case 'city': return '🏙️';
      case 'village': return '🏘️';
      case 'airport': return '✈️';
      case 'building': return '🏢';
      case 'amenity': return '📍';
      case 'natural': return '🌍';
      default: return '📍';
    }
  };

  return (
    <div className="search-bar-container" ref={suggestionsRef}>
      <div className="search-input-wrapper">
        <span className="search-icon">🔍</span>
        
        <input
          ref={searchInputRef}
          type="text"
          value={searchTerm}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          placeholder="Search locations or enter coordinates (35.7262, 51.2721)"
          className={`search-input ${error ? 'error' : ''}`}
          disabled={isLoading}
        />
        
        {searchTerm && (
          <button 
            onClick={handleClear}
            className="clear-button"
            title="Clear search"
            disabled={isLoading}
          >
            ✕
          </button>
        )}
        
        <button 
          onClick={handleSearch}
          className="search-button"
          disabled={isLoading || !searchTerm.trim()}
          title="Search location"
        >
          {isLoading ? (
            <span className="spinner">⟳</span>
          ) : (
            '→'
          )}
        </button>
      </div>

      {/* Error display */}
      {error && (
        <div className="search-error">
          {error}
        </div>
      )}

      {/* Suggestions dropdown */}
      {showSuggestions && suggestions.length > 0 && (
        <div className="search-suggestions">
          {suggestions.map((suggestion, index) => (
            <div
              key={`${suggestion.latitude}-${suggestion.longitude}-${index}`}
              className={`suggestion-item ${index === selectedIndex ? 'selected' : ''}`}
              onClick={() => handleSuggestionSelect(suggestion)}
            >
              <span className="suggestion-icon">
                {getLocationIcon(suggestion.type)}
              </span>
              <div className="suggestion-text">
                <div className="suggestion-main">{suggestion.name}</div>
                <div className="suggestion-sub">
                  {suggestion.description} • {suggestion.latitude.toFixed(4)}, {suggestion.longitude.toFixed(4)}
                </div>
              </div>
            </div>
          ))}
          
          {/* Coordinate parsing hint */}
          <div className="suggestion-hint">
            💡 Tip: Enter coordinates as "latitude, longitude" (e.g., "35.7262, 51.2721")
          </div>
        </div>
      )}

      {/* Loading state for suggestions */}
      {isLoading && searchTerm.length >= 2 && (
        <div className="search-suggestions loading">
          <div className="suggestion-item loading-item">
            <span className="spinner">⟳</span>
            <span>Searching locations...</span>
          </div>
        </div>
      )}

      {/* No results message */}
      {showSuggestions && !isLoading && suggestions.length === 0 && searchTerm.length >= 2 && (
        <div className="search-suggestions">
          <div className="suggestion-item no-results">
            <span>🔍</span>
            <div className="suggestion-text">
              <div className="suggestion-main">No locations found</div>
              <div className="suggestion-sub">Try entering coordinates as "latitude, longitude"</div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

SearchBar.propTypes = {
  onLocationSelect: PropTypes.func.isRequired,
};

export default SearchBar;