// src/utilities/TrajectoryStorage.js

import {
  ALTITUDE_REFERENCE,
  TIMING_MODES,
  validateWaypointSequence,
  calculateTrajectoryStats,
} from './SpeedCalculator';
import { serializeTrajectoryCsv } from './trajectoryCsv';
import { TRAJECTORY_ALTITUDE_POLICY } from '../constants/trajectoryMissionPolicy';

/**
 * TrajectoryStorage - Professional trajectory persistence
 * Features:
 * - Local storage with validation
 * - Auto-backup functionality
 * - Import/export capabilities
 * - Version management
 * - Data integrity checks
 */
export class TrajectoryStorage {
  constructor() {
    this.storageKey = 'drone_trajectory_data';
    this.backupPrefix = 'drone_trajectory_backup_';
    this.maxBackups = 10;
    this.version = '2.0';
  }

  /**
   * Save trajectory to local storage
   */
  async saveTrajectory(name, waypoints, metadata = {}) {
    try {
      const normalizedName = String(name || '').trim();

      if (!normalizedName) {
        throw new Error('Trajectory name is required');
      }

      const trajectoryData = {
        id: this.generateId(),
        name: normalizedName,
        waypoints: this.sanitizeWaypoints(waypoints),
        metadata: {
          ...metadata,
          createdAt: Date.now(),
          modifiedAt: Date.now(),
          version: this.version,
          waypointCount: waypoints.length,
          stats: calculateTrajectoryStats(waypoints)
        }
      };

      // Validate trajectory before saving
      const validation = this.validateTrajectoryData(trajectoryData);
      if (!validation.valid) {
        throw new Error(`Trajectory validation failed: ${validation.issues.join(', ')}`);
      }

      // Get existing trajectories
      const existingTrajectories = this.getAllTrajectories();
      
      // Check if name already exists
      const existingIndex = existingTrajectories.findIndex(t => t.name === normalizedName);
      
      if (existingIndex >= 0) {
        // Update existing
        trajectoryData.id = existingTrajectories[existingIndex].id;
        trajectoryData.metadata.createdAt = existingTrajectories[existingIndex].metadata.createdAt;
        existingTrajectories[existingIndex] = trajectoryData;
      } else {
        // Add new
        existingTrajectories.push(trajectoryData);
      }

      // Save to storage
      await this.setStorageData(this.storageKey, {
        trajectories: existingTrajectories,
        lastModified: Date.now()
      });

      // Create backup
      await this.createBackup();

      return {
        success: true,
        id: trajectoryData.id,
        message: existingIndex >= 0 ? 'Trajectory updated successfully' : 'Trajectory saved successfully'
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Load trajectory by name or ID
   */
  async loadTrajectory(identifier) {
    try {
      const trajectories = this.getAllTrajectories();
      
      const trajectory = trajectories.find(t => 
        t.name === identifier || t.id === identifier
      );

      if (!trajectory) {
        throw new Error(`Trajectory "${identifier}" not found`);
      }

      // Validate loaded trajectory
      const validation = this.validateTrajectoryData(trajectory);
      if (!validation.valid) {
        trajectory.metadata = {
          ...trajectory.metadata,
          validationIssues: validation.issues,
        };
      }

      // Update last accessed
      trajectory.metadata.lastAccessed = Date.now();
      await this.updateTrajectory(trajectory);

      return {
        success: true,
        trajectory: trajectory
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Get all saved trajectories
   */
  getAllTrajectories() {
    try {
      const data = this.getStorageData(this.storageKey);
      return data?.trajectories || [];
    } catch (error) {
      return [];
    }
  }

  /**
   * Delete trajectory by name or ID
   */
  async deleteTrajectory(identifier) {
    try {
      const trajectories = this.getAllTrajectories();
      const initialLength = trajectories.length;
      
      const filteredTrajectories = trajectories.filter(t => 
        t.name !== identifier && t.id !== identifier
      );

      if (filteredTrajectories.length === initialLength) {
        throw new Error(`Trajectory "${identifier}" not found`);
      }

      await this.setStorageData(this.storageKey, {
        trajectories: filteredTrajectories,
        lastModified: Date.now()
      });

      return {
        success: true,
        message: 'Trajectory deleted successfully'
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Export trajectory to file
   */
  async exportTrajectory(identifier, format = 'json') {
    try {
      const result = await this.loadTrajectory(identifier);
      if (!result.success) {
        throw new Error(result.error);
      }

      const { content, filename, mimeType } = this.buildExportFile(result.trajectory, format);

      // Create download
      this.downloadFile(content, filename, mimeType);

      return {
        success: true,
        message: `Trajectory exported as ${format.toUpperCase()}`
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Export the current in-memory planner trajectory without requiring a prior save.
   */
  async exportCurrentTrajectory(name, waypoints, format = 'json', metadata = {}) {
    try {
      const normalizedName = String(name || '').trim() || 'trajectory';
      const trajectory = {
        id: this.generateId(),
        name: normalizedName,
        waypoints: this.sanitizeWaypoints(waypoints),
        metadata: {
          exportedAt: Date.now(),
          version: this.version,
          ...metadata,
        },
      };

      const { content, filename, mimeType } = this.buildExportFile(trajectory, format);
      this.downloadFile(content, filename, mimeType);

      return {
        success: true,
        message: `Trajectory exported as ${format.toUpperCase()}`
      };
    } catch (error) {
      return {
        success: false,
        error: error.message,
      };
    }
  }

  buildPersistenceSignature(name, waypoints = []) {
    const normalizedName = String(name || '').trim();

    return JSON.stringify({
      name: normalizedName,
      waypoints: this.sanitizeWaypoints(waypoints),
    });
  }

  /**
   * Import trajectory from file
   */
  async importTrajectory(file) {
    try {
      const content = await this.readFileContent(file);
      let trajectoryData;

      const fileExtension = file.name.split('.').pop().toLowerCase();

      switch (fileExtension) {
        case 'json':
          trajectoryData = JSON.parse(content);
          break;

        case 'csv':
          trajectoryData = this.parseCSV(content, file.name);
          break;

        default:
          throw new Error(`Unsupported import format: ${fileExtension}`);
      }

      // Validate imported data
      const validation = this.validateTrajectoryData(trajectoryData);
      if (!validation.valid) {
        throw new Error(`Import validation failed: ${validation.issues.join(', ')}`);
      }

      // Generate new ID and update metadata
      trajectoryData.id = this.generateId();
      trajectoryData.metadata = {
        ...trajectoryData.metadata,
        importedAt: Date.now(),
        modifiedAt: Date.now(),
        version: this.version
      };
      const existingTrajectory = this.getAllTrajectories().find(
        (trajectory) => trajectory.name === trajectoryData.name
      );
      
      return {
        success: true,
        trajectory: trajectoryData,
        nameConflict: Boolean(existingTrajectory),
        existingTrajectoryId: existingTrajectory?.id || '',
        message: 'Trajectory imported into planner draft'
      };

    } catch (error) {
      return {
        success: false,
        error: error.message
      };
    }
  }

  /**
   * Auto-save current trajectory
   */
  async autoSave(waypoints, metadata = {}) {
    const autoSaveName = '_autosave_' + new Date().toISOString().split('T')[0];
    
    try {
      await this.saveTrajectory(autoSaveName, waypoints, {
        ...metadata,
        isAutoSave: true
      });
      
      // Keep only latest autosave
      this.cleanupAutoSaves();
      
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Create backup of all trajectories
   */
  async createBackup() {
    try {
      const data = this.getStorageData(this.storageKey);
      const backupKey = this.backupPrefix + Date.now();
      
      await this.setStorageData(backupKey, {
        ...data,
        backupCreatedAt: Date.now()
      });

      // Cleanup old backups
      this.cleanupBackups();
      
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    }
  }

  /**
   * Get storage usage statistics
   */
  getStorageStats() {
    const trajectories = this.getAllTrajectories();
    const totalWaypoints = trajectories.reduce((sum, t) => sum + t.waypoints.length, 0);
    
    let storageUsed = 0;
    try {
      const data = JSON.stringify(this.getStorageData(this.storageKey) || {});
      storageUsed = new Blob([data]).size;
    } catch {
    }

    return {
      trajectoryCount: trajectories.length,
      totalWaypoints,
      storageUsed: this.formatBytes(storageUsed),
      lastModified: trajectories.length > 0 
        ? Math.max(...trajectories.map(t => t.metadata.modifiedAt || 0))
        : null
    };
  }

  // === PRIVATE METHODS ===

  /**
   * Validate trajectory data structure
   */
  validateTrajectoryData(trajectory) {
    const issues = [];

    if (!trajectory.name || typeof trajectory.name !== 'string') {
      issues.push('Trajectory name is required');
    }

    if (!Array.isArray(trajectory.waypoints)) {
      issues.push('Waypoints must be an array');
    } else {
      const waypointValidation = validateWaypointSequence(trajectory.waypoints);
      if (!waypointValidation.valid) {
        issues.push(...waypointValidation.issues.map(issue => issue.message));
      }
    }

    return {
      valid: issues.length === 0,
      issues
    };
  }

  /**
   * SANITIZE WAYPOINTS DATA (Aviation Standard)
   * 
   * Clean, professional waypoint data structure:
   * 
   * CORE FLIGHT DATA:
   * - heading: 0-360° aviation standard (000° = North)
   * - headingMode: 'auto' or 'manual' (single source of truth)
   * - calculatedHeading: auto heading for the arrival leg (for UI display)
   * 
   * BACKWARDS COMPATIBILITY:
   * - Automatically converts old 'yaw'/'yawMode' fields
   * - Maintains seamless upgrade path for existing trajectories
   */
  sanitizeWaypoints(waypoints) {
    return waypoints.map((wp, index) => ({
      // Standard waypoint data
      id: wp.id || `waypoint-${Date.now()}-${index}`,
      name: wp.name || `Waypoint ${index + 1}`,
      latitude: Number(wp.latitude),
      longitude: Number(wp.longitude),
      altitude: Number(wp.altitude),
      altitudeReference: wp.altitudeReference || ALTITUDE_REFERENCE.MSL,
      targetAgl: Number(wp.targetAgl || 0),
      timeFromStart: Number(wp.timeFromStart || wp.time || 0),
      timingMode: wp.timingMode || TIMING_MODES.MANUAL_TIME,
      preferredSpeed: Number(wp.preferredSpeed || 0),
      estimatedSpeed: Number(wp.estimatedSpeed || 0),
      speedFeasible: Boolean(wp.speedFeasible),
      groundElevation: Number(wp.groundElevation || 0),
      terrainAccurate: wp.terrainAccurate !== false,
      
      // AVIATION STANDARD HEADING DATA (clean, single source of truth)
      heading: wp.heading !== undefined ? Number(wp.heading) : (wp.yaw !== undefined ? Number(wp.yaw) : 0),
      headingMode: wp.headingMode || wp.yawMode || 'auto',  // 'auto' or 'manual' - determines all behavior
      calculatedHeading: wp.calculatedHeading !== undefined ? Number(wp.calculatedHeading) : (wp.calculatedYaw !== undefined ? Number(wp.calculatedYaw) : 0)
    }));
  }

  /**
   * Convert waypoints to CSV format (aviation standard)
   * Clean, single-source-of-truth approach: HeadingMode contains all needed info
   */
  convertToCSV(waypoints) {
    return serializeTrajectoryCsv(waypoints);
  }

  /**
   * Convert trajectory to KML format
   */
  convertToKML(trajectory) {
    const coordinates = trajectory.waypoints
      .map(wp => `${wp.longitude},${wp.latitude},${wp.altitude}`)
      .join(' ');

    return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>${trajectory.name}</name>
    <description>Drone trajectory with ${trajectory.waypoints.length} waypoints</description>
    <Placemark>
      <name>Trajectory Path</name>
      <LineString>
        <coordinates>${coordinates}</coordinates>
      </LineString>
    </Placemark>
    ${trajectory.waypoints.map((wp, index) => `
    <Placemark>
      <name>${wp.name}</name>
      <description>Altitude: ${wp.altitude}m MSL, Time: ${wp.timeFromStart}s, Heading: ${(wp.heading || wp.yaw || 0).toFixed(0).padStart(3, '0')}° (${(wp.headingMode || wp.yawMode) === 'auto' ? 'Auto' : 'Manual'})</description>
      <Point>
        <coordinates>${wp.longitude},${wp.latitude},${wp.altitude}</coordinates>
      </Point>
    </Placemark>`).join('')}
  </Document>
</kml>`;
  }

  buildExportFile(trajectory, format = 'json') {
    const safeName = (trajectory.name || 'trajectory').replace(/[^a-z0-9]/gi, '_');

    switch (format.toLowerCase()) {
      case 'json':
        return {
          content: JSON.stringify(trajectory, null, 2),
          filename: `${safeName}.json`,
          mimeType: 'application/json',
        };
      case 'csv':
        return {
          content: this.convertToCSV(trajectory.waypoints),
          filename: `${safeName}.csv`,
          mimeType: 'text/csv',
        };
      case 'kml':
        return {
          content: this.convertToKML(trajectory),
          filename: `${safeName}.kml`,
          mimeType: 'application/vnd.google-earth.kml+xml',
        };
      default:
        throw new Error(`Unsupported export format: ${format}`);
    }
  }

  /**
   * Parse CSV content to trajectory data
   */
  parseCSV(content, filename) {
    const lines = content.trim().split('\n').filter((line) => line.trim().length > 0);
    const headers = (lines[0] || '').split(',').map((value) => value.trim());
    const headerIndex = new Map(headers.map((header, index) => [header, index]));
    const readValue = (values, headerName, fallbackIndex, fallbackValue = '') => {
      const index = headerIndex.get(headerName);

      if (index !== undefined) {
        return values[index] ?? fallbackValue;
      }

      return values[fallbackIndex] ?? fallbackValue;
    };
    const normalizeAltitudeReference = (value) =>
      String(value || '').toLowerCase() === ALTITUDE_REFERENCE.AGL ? ALTITUDE_REFERENCE.AGL : ALTITUDE_REFERENCE.MSL;
    const normalizeTimingMode = (value) =>
      String(value || '').toLowerCase() === TIMING_MODES.AUTO_SPEED ? TIMING_MODES.AUTO_SPEED : TIMING_MODES.MANUAL_TIME;
    const normalizeHeadingMode = (value) =>
      String(value || '').toLowerCase() === 'manual' ? 'manual' : 'auto';
    
    const waypoints = lines.slice(1).map((line, index) => {
      const values = line.split(',').map(v => v.trim());
      const altitudeReference = normalizeAltitudeReference(readValue(values, 'AltitudeReference', 8, ALTITUDE_REFERENCE.MSL));
      const targetAgl = parseFloat(readValue(values, 'TargetAgl_m', 9, '0')) || 0;
      const groundElevation = parseFloat(readValue(values, 'GroundElevation_m', 10, '0')) || 0;
      const terrainAccurateRaw = readValue(values, 'TerrainAccurate', 11, 'true');
      const terrainAccurate = String(terrainAccurateRaw).toLowerCase() !== 'false';
      const timingMode = normalizeTimingMode(readValue(values, 'TimingMode', 12, TIMING_MODES.MANUAL_TIME));
      const preferredSpeed = parseFloat(readValue(values, 'PreferredSpeed_ms', 13, '0')) || 0;
      const calculatedHeading = parseFloat(readValue(values, 'CalculatedHeading_deg', 14, '0')) || 0;

      return {
        id: `waypoint-${Date.now()}-${index}`,
        name: readValue(values, 'Name', 0, `Waypoint ${index + 1}`) || `Waypoint ${index + 1}`,
        latitude: parseFloat(readValue(values, 'Latitude', 1, '0')) || 0,
        longitude: parseFloat(readValue(values, 'Longitude', 2, '0')) || 0,
        altitude: parseFloat(readValue(values, 'Altitude_MSL_m', 3, String(TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL))) || TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL,
        altitudeReference,
        targetAgl,
        groundElevation,
        terrainAccurate,
        timeFromStart: parseFloat(readValue(values, 'TimeFromStart_s', 4, '0')) || 0,
        timingMode,
        preferredSpeed,
        estimatedSpeed: parseFloat(readValue(values, 'EstimatedSpeed_ms', 5, '0')) || 0,
        speedFeasible: true,
        // Aviation standard heading data with backwards compatibility
        heading: parseFloat(readValue(values, 'Heading_deg', 6, '0')) || 0,
        headingMode: normalizeHeadingMode(readValue(values, 'HeadingMode', 7, 'auto')),
        calculatedHeading,
      };
    });

    return {
      name: filename.replace(/\.[^/.]+$/, ''),
      waypoints,
      metadata: {
        importedFrom: 'csv',
        originalFilename: filename
      }
    };
  }

  /**
   * Generic storage operations
   */
  getStorageData(key) {
    try {
      const data = localStorage.getItem(key);
      return data ? JSON.parse(data) : null;
    } catch {
      return null;
    }
  }

  async setStorageData(key, data) {
    try {
      localStorage.setItem(key, JSON.stringify(data));
    } catch (error) {
      if (error.name === 'QuotaExceededError') {
        await this.handleStorageQuotaExceeded();
        throw new Error('Storage quota exceeded. Please delete old trajectories.');
      }
      throw error;
    }
  }

  /**
   * Handle storage quota exceeded
   */
  async handleStorageQuotaExceeded() {
    // Remove old backups first
    this.cleanupBackups(5);
    
    // Remove old autosaves
    this.cleanupAutoSaves();
    
  }

  /**
   * Update existing trajectory
   */
  async updateTrajectory(trajectory) {
    const trajectories = this.getAllTrajectories();
    const index = trajectories.findIndex(t => t.id === trajectory.id);
    
    if (index >= 0) {
      trajectories[index] = trajectory;
      await this.setStorageData(this.storageKey, {
        trajectories,
        lastModified: Date.now()
      });
    }
  }

  /**
   * Cleanup old auto-saves
   */
  cleanupAutoSaves() {
    const trajectories = this.getAllTrajectories();
    const autoSaves = trajectories.filter(t => t.metadata?.isAutoSave);
    
    if (autoSaves.length > 1) {
      // Keep only the most recent autosave
      const sorted = autoSaves.sort((a, b) => b.metadata.modifiedAt - a.metadata.modifiedAt);
      const toDelete = sorted.slice(1);
      
      toDelete.forEach(autosave => {
        this.deleteTrajectory(autosave.id);
      });
    }
  }

  /**
   * Cleanup old backups
   */
  cleanupBackups(maxKeep = this.maxBackups) {
    const backupKeys = Object.keys(localStorage)
      .filter(key => key.startsWith(this.backupPrefix))
      .sort()
      .reverse();

    if (backupKeys.length > maxKeep) {
      const toDelete = backupKeys.slice(maxKeep);
      toDelete.forEach(key => {
        localStorage.removeItem(key);
      });
    }
  }

  /**
   * Generate unique ID
   */
  generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
  }

  /**
   * Format bytes for display
   */
  formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  /**
   * Read file content
   */
  readFileContent(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = e => resolve(e.target.result);
      reader.onerror = e => reject(new Error('File read error'));
      reader.readAsText(file);
    });
  }

  /**
   * Download file
   */
  downloadFile(content, filename, mimeType) {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    
    link.href = url;
    link.download = filename;
    link.style.display = 'none';
    
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    
    URL.revokeObjectURL(url);
  }
}
