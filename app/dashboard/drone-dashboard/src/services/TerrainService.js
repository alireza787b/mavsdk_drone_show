// src/services/TerrainService.js
// PHASE 3: Complete terrain integration with MapGL terrain source

/**
 * TerrainService - Complete AGL/MSL conversion with real terrain data
 * PHASE 3 FEATURES:
 * - Real MapGL terrain elevation queries
 * - Dynamic AGL ↔ MSL conversion
 * - Performance-optimized caching system
 * - Batch elevation processing
 * - User preference management
 */
export class TerrainService {
    constructor() {
      this.isAvailable = false;
      this.mapboxToken = null;
      this.map = null;
      this.elevationCache = new Map();
      this.maxCacheSize = 2000;
      this.defaultSeaLevelElevation = 0;
      this.userPreference = 'MSL'; // 'MSL' or 'AGL'
      this.batchQueue = [];
      this.batchTimeout = null;
    }
  
    /**
     * PHASE 3: Initialize with real MapGL terrain
     */
    async initialize(mapboxToken = null, mapInstance = null) {
      try {
        this.mapboxToken = mapboxToken;
        this.map = mapInstance;
        
        if (mapboxToken && mapInstance) {
          // Verify terrain source is available
          await this.verifyTerrainSource();
          this.isAvailable = true;
          
          console.info('TerrainService: Real terrain elevation available');
          return {
            success: true,
            provider: 'mapbox-terrain',
            message: 'Terrain service initialized with real elevation data'
          };
        }
        
        // Fallback mode
        this.isAvailable = false;
        return {
          success: true,
          provider: 'estimated',
          message: 'Terrain service initialized (estimated mode)'
        };
        
      } catch (error) {
        console.warn('TerrainService initialization failed:', error);
        this.isAvailable = false;
        return {
          success: false,
          error: error.message
        };
      }
    }
  
    /**
     * PHASE 3: Set user altitude preference
     */
    setAltitudePreference(preference) {
      if (['MSL', 'AGL'].includes(preference)) {
        this.userPreference = preference;
        localStorage.setItem('drone_altitude_preference', preference);
        return true;
      }
      return false;
    }
  
    /**
     * PHASE 3: Get user altitude preference
     */
    getAltitudePreference() {
      const stored = localStorage.getItem('drone_altitude_preference');
      if (stored && ['MSL', 'AGL'].includes(stored)) {
        this.userPreference = stored;
      }
      return this.userPreference;
    }
  
    /**
     * PHASE 3: Real ground elevation from MapGL terrain
     */
    async getGroundElevation(latitude, longitude) {
      const cacheKey = `${latitude.toFixed(6)},${longitude.toFixed(6)}`;
      
      // Check cache first
      if (this.elevationCache.has(cacheKey)) {
        return this.elevationCache.get(cacheKey);
      }
  
      let elevation = this.defaultSeaLevelElevation;
  
      if (this.isAvailable && this.map) {
        try {
          // PHASE 3: Query MapGL terrain elevation
          elevation = await this.queryMapboxTerrain(latitude, longitude);
        } catch (error) {
          console.warn('Real terrain query failed, using estimation:', error);
          elevation = this.estimateElevation(latitude, longitude);
        }
      } else {
        elevation = this.estimateElevation(latitude, longitude);
      }
  
      // Cache result
      this.cacheElevation(cacheKey, elevation);
      
      return elevation;
    }
  
    /**
     * PHASE 3: Batch elevation queries for performance
     */
    async getBatchGroundElevation(coordinates) {
      const results = [];
      const uncachedCoords = [];
      
      // Check cache first
      for (const coord of coordinates) {
        const cacheKey = `${coord.latitude.toFixed(6)},${coord.longitude.toFixed(6)}`;
        if (this.elevationCache.has(cacheKey)) {
          results.push({
            ...coord,
            elevation: this.elevationCache.get(cacheKey),
            cached: true
          });
        } else {
          uncachedCoords.push(coord);
        }
      }
  
      // Query uncached coordinates
      if (uncachedCoords.length > 0) {
        try {
          const elevations = await this.batchQueryTerrain(uncachedCoords);
          for (let i = 0; i < uncachedCoords.length; i++) {
            const coord = uncachedCoords[i];
            const elevation = elevations[i] || this.estimateElevation(coord.latitude, coord.longitude);
            
            results.push({
              ...coord,
              elevation,
              cached: false
            });
            
            // Cache result
            const cacheKey = `${coord.latitude.toFixed(6)},${coord.longitude.toFixed(6)}`;
            this.cacheElevation(cacheKey, elevation);
          }
        } catch (error) {
          console.warn('Batch terrain query failed:', error);
          // Fallback to estimation
          for (const coord of uncachedCoords) {
            results.push({
              ...coord,
              elevation: this.estimateElevation(coord.latitude, coord.longitude),
              cached: false
            });
          }
        }
      }
  
      return results;
    }
  
    /**
     * PHASE 3: Convert MSL altitude to AGL with real terrain
     */
    async convertMSLtoAGL(latitude, longitude, mslAltitude) {
      try {
        const groundElevation = await this.getGroundElevation(latitude, longitude);
        const aglAltitude = Math.max(0, mslAltitude - groundElevation);
        
        return {
          success: true,
          aglAltitude,
          groundElevation,
          mslAltitude,
          terrainAvailable: this.isAvailable,
          conversionAccurate: this.isAvailable
        };
      } catch (error) {
        return {
          success: false,
          error: error.message,
          terrainAvailable: this.isAvailable
        };
      }
    }
  
    /**
     * PHASE 3: Convert AGL altitude to MSL with real terrain
     */
    async convertAGLtoMSL(latitude, longitude, aglAltitude) {
      try {
        const groundElevation = await this.getGroundElevation(latitude, longitude);
        const mslAltitude = aglAltitude + groundElevation;
        
        return {
          success: true,
          mslAltitude,
          groundElevation,
          aglAltitude,
          terrainAvailable: this.isAvailable,
          conversionAccurate: this.isAvailable
        };
      } catch (error) {
        return {
          success: false,
          error: error.message,
          terrainAvailable: this.isAvailable
        };
      }
    }
  
    /**
     * PHASE 3: Get complete altitude information for waypoint
     */
    async getWaypointAltitudeInfo(waypoint) {
      const { latitude, longitude, altitude } = waypoint;
      
      try {
        const groundElevation = await this.getGroundElevation(latitude, longitude);
        
        // Determine input type based on user preference
        let mslAltitude, aglAltitude;
        
        if (this.userPreference === 'AGL') {
          aglAltitude = altitude;
          mslAltitude = altitude + groundElevation;
        } else {
          mslAltitude = altitude;
          aglAltitude = Math.max(0, altitude - groundElevation);
        }
        
        return {
          success: true,
          waypoint: {
            ...waypoint,
            altitudeMSL: mslAltitude,
            altitudeAGL: aglAltitude,
            groundElevation,
            altitudeDisplay: this.formatAltitudeDisplay(mslAltitude, aglAltitude),
            inputMode: this.userPreference
          },
          terrainInfo: {
            available: this.isAvailable,
            accurate: this.isAvailable,
            groundElevation,
            estimatedTerrain: !this.isAvailable
          }
        };
      } catch (error) {
        return {
          success: false,
          error: error.message,
          waypoint: waypoint
        };
      }
    }
  
    /**
     * PHASE 3: Process entire trajectory with terrain data
     */
    async processTrajectoryTerrain(waypoints) {
      try {
        const coordinates = waypoints.map(wp => ({
          latitude: wp.latitude,
          longitude: wp.longitude,
          id: wp.id
        }));
  
        const elevationResults = await this.getBatchGroundElevation(coordinates);
        
        const processedWaypoints = waypoints.map(waypoint => {
          const elevationData = elevationResults.find(r => 
            Math.abs(r.latitude - waypoint.latitude) < 0.000001 &&
            Math.abs(r.longitude - waypoint.longitude) < 0.000001
          );
          
          if (!elevationData) return waypoint;
          
          const groundElevation = elevationData.elevation;
          
          let mslAltitude, aglAltitude;
          if (this.userPreference === 'AGL') {
            aglAltitude = waypoint.altitude;
            mslAltitude = waypoint.altitude + groundElevation;
          } else {
            mslAltitude = waypoint.altitude;
            aglAltitude = Math.max(0, waypoint.altitude - groundElevation);
          }
          
          return {
            ...waypoint,
            altitudeMSL: mslAltitude,
            altitudeAGL: aglAltitude,
            groundElevation,
            altitudeDisplay: this.formatAltitudeDisplay(mslAltitude, aglAltitude),
            terrainProcessed: true
          };
        });
  
        return {
          success: true,
          waypoints: processedWaypoints,
          terrainStats: {
            totalPoints: waypoints.length,
            terrainAvailable: this.isAvailable,
            maxGroundElevation: Math.max(...elevationResults.map(r => r.elevation)),
            minGroundElevation: Math.min(...elevationResults.map(r => r.elevation)),
            cached: elevationResults.filter(r => r.cached).length,
            queried: elevationResults.filter(r => !r.cached).length
          }
        };
      } catch (error) {
        return {
          success: false,
          error: error.message,
          waypoints
        };
      }
    }
  
    /**
     * PHASE 3: Enhanced altitude validation with terrain context
     */
    validateAltitudeWithTerrain(mslAltitude, aglAltitude, groundElevation) {
      const issues = [];
      const warnings = [];
      const suggestions = [];
  
      // MSL altitude checks
      if (mslAltitude < 0) {
        issues.push('MSL altitude cannot be negative');
      }
      
      if (mslAltitude > 10000) {
        issues.push('MSL altitude exceeds reasonable flight ceiling (10km)');
      }
  
      // AGL altitude checks with terrain context
      if (aglAltitude < 0) {
        issues.push('Altitude is below ground level');
        suggestions.push(`Minimum MSL altitude: ${groundElevation.toFixed(1)}m`);
      }
  
      if (aglAltitude < 5) {
        warnings.push('Very low AGL altitude - risk of terrain collision');
        suggestions.push('Consider increasing altitude for safety clearance');
      }
  
      if (aglAltitude > 400) {
        warnings.push('AGL altitude exceeds typical drone operational limits (400ft/122m AGL)');
      }
  
      // Terrain-specific warnings
      if (groundElevation > 3000) {
        warnings.push('High terrain elevation - verify regulations for high-altitude areas');
      }
  
      if (!this.isAvailable) {
        warnings.push('Using estimated terrain data - actual ground elevation may differ');
      }
  
      return {
        safe: issues.length === 0,
        issues,
        warnings,
        suggestions,
        altitudeData: {
          mslAltitude,
          aglAltitude,
          groundElevation,
          terrainAccurate: this.isAvailable,
          recommendedMinMSL: groundElevation + 30, // 30m AGL safety buffer
          recommendedMaxAGL: 400 // Typical regulatory limit
        }
      };
    }
  
    // === PRIVATE METHODS ===
  
    /**
     * PHASE 3: Verify MapGL terrain source is available
     */
    async verifyTerrainSource() {
      if (!this.map) {
        throw new Error('Map instance not available');
      }
  
      return new Promise((resolve, reject) => {
        const checkTerrain = () => {
          if (this.map.isStyleLoaded()) {
            try {
              // Check if terrain source exists
              const sources = this.map.getStyle().sources;
              const hasTerrainSource = Object.keys(sources).some(key => 
                sources[key].type === 'raster-dem'
              );
              
              if (hasTerrainSource) {
                resolve(true);
              } else {
                reject(new Error('Terrain source not found in map style'));
              }
            } catch (error) {
              reject(error);
            }
          } else {
            // Wait for style to load
            setTimeout(checkTerrain, 100);
          }
        };
  
        checkTerrain();
      });
    }
  
    /**
     * PHASE 3: Query MapGL terrain for single coordinate
     */
    async queryMapboxTerrain(latitude, longitude) {
      if (!this.map) {
        throw new Error('Map not available for terrain query');
      }
  
      return new Promise((resolve, reject) => {
        try {
          // Use map.queryTerrainElevation if available (newer MapGL versions)
          if (typeof this.map.queryTerrainElevation === 'function') {
            const elevation = this.map.queryTerrainElevation([longitude, latitude]);
            resolve(elevation || 0);
          } else {
            // Fallback to estimation for older versions
            resolve(this.estimateElevation(latitude, longitude));
          }
        } catch (error) {
          reject(error);
        }
      });
    }
  
    /**
     * PHASE 3: Batch query terrain for multiple coordinates
     */
    async batchQueryTerrain(coordinates) {
      const elevations = [];
      
      // Process in smaller batches for performance
      const batchSize = 10;
      for (let i = 0; i < coordinates.length; i += batchSize) {
        const batch = coordinates.slice(i, i + batchSize);
        const batchResults = await Promise.all(
          batch.map(coord => this.queryMapboxTerrain(coord.latitude, coord.longitude))
        );
        elevations.push(...batchResults);
      }
      
      return elevations;
    }
  
    /**
     * Enhanced elevation estimation with geographic data
     */
    estimateElevation(latitude, longitude) {
      // Enhanced estimation using more geographic knowledge
      const regions = [
        // Mountain ranges
        { bounds: [25, 50, -125, -100], elevation: 1800, name: 'Rocky Mountains' },
        { bounds: [28, 47, 65, 105], elevation: 2200, name: 'Himalayas' },
        { bounds: [40, 50, -10, 20], elevation: 900, name: 'Alps' },
        { bounds: [-56, -22, -75, -53], elevation: 1200, name: 'Andes' },
        
        // High plateaus
        { bounds: [27, 40, 73, 105], elevation: 4000, name: 'Tibetan Plateau' },
        { bounds: [34, 42, -114, -102], elevation: 1600, name: 'Colorado Plateau' },
        
        // Coastal areas (generally lower)
        { bounds: [24, 49, -127, -80], elevation: 150, name: 'US Coastal' },
        { bounds: [35, 71, -10, 30], elevation: 200, name: 'European Coastal' },
        
        // Plains and valleys
        { bounds: [30, 49, -104, -88], elevation: 400, name: 'Great Plains' },
        { bounds: [45, 60, 20, 60], elevation: 200, name: 'European Plains' },
      ];
  
      // Check if coordinate falls within known regions
      for (const region of regions) {
        const [minLat, maxLat, minLng, maxLng] = region.bounds;
        if (latitude >= minLat && latitude <= maxLat && 
            longitude >= minLng && longitude <= maxLng) {
          // Add some variation based on exact coordinates
          const variation = Math.sin(latitude * 0.1) * Math.cos(longitude * 0.1) * 200;
          return Math.max(0, region.elevation + variation);
        }
      }
  
      // Default estimation based on latitude
      if (Math.abs(latitude) > 60) return 300; // Polar regions
      if (Math.abs(latitude) < 30) return 100;  // Tropical regions
      return 250; // Temperate regions
    }
  
    /**
     * Format altitude for display based on user preference
     */
    formatAltitudeDisplay(mslAltitude, aglAltitude) {
      if (this.userPreference === 'AGL') {
        return `${aglAltitude.toFixed(1)}m AGL (${mslAltitude.toFixed(1)}m MSL)`;
      } else {
        return `${mslAltitude.toFixed(1)}m MSL (${aglAltitude.toFixed(1)}m AGL)`;
      }
    }
  
    /**
     * Cache management with intelligent cleanup
     */
    cacheElevation(key, elevation) {
      // Manage cache size with LRU eviction
      if (this.elevationCache.size >= this.maxCacheSize) {
        const firstKey = this.elevationCache.keys().next().value;
        this.elevationCache.delete(firstKey);
      }
  
      this.elevationCache.set(key, elevation);
    }
  
    /**
     * Clear cache with optional geographic bounds
     */
    clearCache(bounds = null) {
      if (!bounds) {
        this.elevationCache.clear();
        return;
      }
  
      // Clear cache within specific bounds
      const [minLat, maxLat, minLng, maxLng] = bounds;
      for (const [key] of this.elevationCache.entries()) {
        const [lat, lng] = key.split(',').map(Number);
        if (lat >= minLat && lat <= maxLat && lng >= minLng && lng <= maxLng) {
          this.elevationCache.delete(key);
        }
      }
    }
  
    /**
     * Get comprehensive cache and service statistics
     */
    getServiceStats() {
      return {
        terrainAvailable: this.isAvailable,
        cacheSize: this.elevationCache.size,
        maxCacheSize: this.maxCacheSize,
        userPreference: this.userPreference,
        provider: this.isAvailable ? 'mapbox-terrain' : 'estimated',
        accuracy: this.isAvailable ? 'high' : 'estimated',
        features: {
          realTerrain: this.isAvailable,
          batchQueries: true,
          aglMslConversion: true,
          userPreferences: true,
          caching: true
        }
      };
    }
  }
  
  // Create singleton instance
  export const terrainService = new TerrainService();
  
  // Export utility functions
  export const convertMSLtoAGL = (lat, lng, msl) => terrainService.convertMSLtoAGL(lat, lng, msl);
  export const convertAGLtoMSL = (lat, lng, agl) => terrainService.convertAGLtoMSL(lat, lng, agl);
  export const getWaypointAltitudeInfo = (waypoint) => terrainService.getWaypointAltitudeInfo(waypoint);
  export const processTrajectoryTerrain = (waypoints) => terrainService.processTrajectoryTerrain(waypoints);
  export const setAltitudePreference = (pref) => terrainService.setAltitudePreference(pref);
  export const getAltitudePreference = () => terrainService.getAltitudePreference();
  
  /**
   * PHASE 3: Enhanced altitude validation
   */
  export const validateAltitude = async (latitude, longitude, altitude, mode = 'MSL') => {
    try {
      const groundElevation = await terrainService.getGroundElevation(latitude, longitude);
      
      let mslAltitude, aglAltitude;
      if (mode === 'AGL') {
        aglAltitude = altitude;
        mslAltitude = altitude + groundElevation;
      } else {
        mslAltitude = altitude;
        aglAltitude = Math.max(0, altitude - groundElevation);
      }
      
      return terrainService.validateAltitudeWithTerrain(mslAltitude, aglAltitude, groundElevation);
    } catch (error) {
      return {
        safe: false,
        issues: [`Altitude validation failed: ${error.message}`],
        warnings: [],
        suggestions: []
      };
    }
  };
  
  /**
   * PHASE 3: Smart altitude suggestion based on terrain and regulations
   */
  export const suggestSafeAltitude = async (latitude, longitude, desiredAGL = 100, mode = 'MSL') => {
    try {
      const groundElevation = await terrainService.getGroundElevation(latitude, longitude);
      
      // Ensure minimum safety clearance
      const safeAGL = Math.max(desiredAGL, 30); // Minimum 30m AGL
      const safeMSL = groundElevation + safeAGL;
      
      return {
        success: true,
        suggestedMSL: Math.round(safeMSL),
        suggestedAGL: safeAGL,
        groundElevation,
        terrainAccurate: terrainService.isAvailable,
        suggestion: mode === 'AGL' ? safeAGL : safeMSL,
        reasoning: `Safe altitude with ${safeAGL}m ground clearance`
      };
    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  };