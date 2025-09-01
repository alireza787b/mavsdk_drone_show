// src/utilities/TrajectoryStorage.js
// PHASE 2: Professional save/load functionality with validation and backup

import { validateWaypointSequence, calculateTrajectoryStats } from './SpeedCalculator';

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
      const trajectoryData = {
        id: this.generateId(),
        name: name.trim(),
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
      const existingIndex = existingTrajectories.findIndex(t => t.name === name);
      
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
      console.error('Save trajectory error:', error);
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
        console.warn('Loaded trajectory has validation issues:', validation.issues);
      }

      // Update last accessed
      trajectory.metadata.lastAccessed = Date.now();
      await this.updateTrajectory(trajectory);

      return {
        success: true,
        trajectory: trajectory
      };

    } catch (error) {
      console.error('Load trajectory error:', error);
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
      console.error('Get trajectories error:', error);
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
      console.error('Delete trajectory error:', error);
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

      const trajectory = result.trajectory;
      let content, filename, mimeType;

      switch (format.toLowerCase()) {
        case 'json':
          content = JSON.stringify(trajectory, null, 2);
          filename = `${trajectory.name.replace(/[^a-z0-9]/gi, '_')}.json`;
          mimeType = 'application/json';
          break;

        case 'csv':
          content = this.convertToCSV(trajectory.waypoints);
          filename = `${trajectory.name.replace(/[^a-z0-9]/gi, '_')}.csv`;
          mimeType = 'text/csv';
          break;

        case 'kml':
          content = this.convertToKML(trajectory);
          filename = `${trajectory.name.replace(/[^a-z0-9]/gi, '_')}.kml`;
          mimeType = 'application/vnd.google-earth.kml+xml';
          break;

        default:
          throw new Error(`Unsupported export format: ${format}`);
      }

      // Create download
      this.downloadFile(content, filename, mimeType);

      return {
        success: true,
        message: `Trajectory exported as ${format.toUpperCase()}`
      };

    } catch (error) {
      console.error('Export trajectory error:', error);
      return {
        success: false,
        error: error.message
      };
    }
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

      // Save imported trajectory
      const saveResult = await this.saveTrajectory(trajectoryData.name, trajectoryData.waypoints, trajectoryData.metadata);
      
      return {
        success: saveResult.success,
        trajectory: trajectoryData,
        message: saveResult.success ? 'Trajectory imported successfully' : saveResult.error
      };

    } catch (error) {
      console.error('Import trajectory error:', error);
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
      console.warn('Auto-save failed:', error);
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
      console.warn('Backup creation failed:', error);
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
    } catch (error) {
      console.warn('Storage size calculation failed:', error);
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
   * Sanitize waypoints data
   */
  sanitizeWaypoints(waypoints) {
    return waypoints.map((wp, index) => ({
      id: wp.id || `waypoint-${Date.now()}-${index}`,
      name: wp.name || `Waypoint ${index + 1}`,
      latitude: Number(wp.latitude),
      longitude: Number(wp.longitude),
      altitude: Number(wp.altitude),
      timeFromStart: Number(wp.timeFromStart || wp.time || 0),
      estimatedSpeed: Number(wp.estimatedSpeed || 0),
      speedFeasible: Boolean(wp.speedFeasible)
    }));
  }

  /**
   * Convert waypoints to CSV format
   */
  convertToCSV(waypoints) {
    const headers = ['Name', 'Latitude', 'Longitude', 'Altitude_MSL_m', 'TimeFromStart_s', 'EstimatedSpeed_ms'];
    const rows = waypoints.map(wp => [
      wp.name,
      wp.latitude.toFixed(8),
      wp.longitude.toFixed(8),
      wp.altitude.toFixed(2),
      (wp.timeFromStart || 0).toFixed(1),
      (wp.estimatedSpeed || 0).toFixed(1)
    ]);

    return [headers, ...rows].map(row => row.join(',')).join('\n');
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
      <description>Altitude: ${wp.altitude}m MSL, Time: ${wp.timeFromStart}s</description>
      <Point>
        <coordinates>${wp.longitude},${wp.latitude},${wp.altitude}</coordinates>
      </Point>
    </Placemark>`).join('')}
  </Document>
</kml>`;
  }

  /**
   * Parse CSV content to trajectory data
   */
  parseCSV(content, filename) {
    const lines = content.trim().split('\n');
    const headers = lines[0].split(',').map(h => h.trim());
    
    const waypoints = lines.slice(1).map((line, index) => {
      const values = line.split(',').map(v => v.trim());
      return {
        id: `waypoint-${Date.now()}-${index}`,
        name: values[0] || `Waypoint ${index + 1}`,
        latitude: parseFloat(values[1]) || 0,
        longitude: parseFloat(values[2]) || 0,
        altitude: parseFloat(values[3]) || 100,
        timeFromStart: parseFloat(values[4]) || 0,
        estimatedSpeed: parseFloat(values[5]) || 0,
        speedFeasible: true
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
    } catch (error) {
      console.warn('Storage read error:', error);
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
    
    console.warn('Storage quota exceeded - cleaned up old data');
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