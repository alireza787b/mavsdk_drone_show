// src/utilities/TrajectoryStateManager.js
// PHASE 2: Professional undo/redo state management for trajectory operations

/**
 * Action types for trajectory operations
 */
export const ACTION_TYPES = {
    ADD_WAYPOINT: 'ADD_WAYPOINT',
    UPDATE_WAYPOINT: 'UPDATE_WAYPOINT', 
    DELETE_WAYPOINT: 'DELETE_WAYPOINT',
    MOVE_WAYPOINT: 'MOVE_WAYPOINT',
    CLEAR_TRAJECTORY: 'CLEAR_TRAJECTORY',
    LOAD_TRAJECTORY: 'LOAD_TRAJECTORY',
    BATCH_UPDATE: 'BATCH_UPDATE'
  };
  
  /**
   * TrajectoryStateManager - Professional state management with undo/redo
   * Features:
   * - Comprehensive action tracking
   * - Efficient state snapshots
   * - Action descriptions for UI
   * - State validation
   * - Memory optimization
   */
  export class TrajectoryStateManager {
    constructor(maxHistorySize = 50) {
      this.maxHistorySize = maxHistorySize;
      this.undoStack = [];
      this.redoStack = [];
      this.currentState = {
        waypoints: [],
        selectedWaypointId: null,
        lastModified: Date.now()
      };
    }
  
    /**
     * Get current state
     */
    getCurrentState() {
      return { ...this.currentState };
    }
  
    /**
     * Execute action and save state for undo
     */
    executeAction(actionType, payload, description = '') {
      // Save current state to undo stack
      this.saveToUndoStack(actionType, description);
      
      // Clear redo stack on new action
      this.redoStack = [];
      
      // Apply the action
      this.applyAction(actionType, payload);
      
      // Optimize memory usage
      this.optimizeStacks();
      
      return this.getCurrentState();
    }
  
    /**
     * Apply action to current state
     */
    applyAction(actionType, payload) {
      const timestamp = Date.now();
      
      switch (actionType) {
        case ACTION_TYPES.ADD_WAYPOINT:
          this.currentState.waypoints = [...this.currentState.waypoints, payload.waypoint];
          this.currentState.selectedWaypointId = payload.waypoint.id;
          break;
          
        case ACTION_TYPES.UPDATE_WAYPOINT:
          this.currentState.waypoints = this.currentState.waypoints.map(wp =>
            wp.id === payload.id ? { ...wp, ...payload.updates } : wp
          );
          break;
          
        case ACTION_TYPES.DELETE_WAYPOINT:
          this.currentState.waypoints = this.currentState.waypoints.filter(
            wp => wp.id !== payload.id
          );
          if (this.currentState.selectedWaypointId === payload.id) {
            this.currentState.selectedWaypointId = null;
          }
          break;
          
        case ACTION_TYPES.MOVE_WAYPOINT:
          this.currentState.waypoints = this.currentState.waypoints.map(wp =>
            wp.id === payload.id 
              ? { ...wp, latitude: payload.latitude, longitude: payload.longitude }
              : wp
          );
          break;
          
        case ACTION_TYPES.CLEAR_TRAJECTORY:
          this.currentState.waypoints = [];
          this.currentState.selectedWaypointId = null;
          break;
          
        case ACTION_TYPES.LOAD_TRAJECTORY:
          this.currentState.waypoints = payload.waypoints || [];
          this.currentState.selectedWaypointId = payload.selectedWaypointId || null;
          break;
          
        case ACTION_TYPES.BATCH_UPDATE:
          this.currentState.waypoints = payload.waypoints || this.currentState.waypoints;
          this.currentState.selectedWaypointId = payload.selectedWaypointId !== undefined 
            ? payload.selectedWaypointId 
            : this.currentState.selectedWaypointId;
          break;
      }
      
      this.currentState.lastModified = timestamp;
    }
  
    /**
     * Save current state to undo stack
     */
    saveToUndoStack(actionType, description) {
      const stateSnapshot = {
        state: this.deepClone(this.currentState),
        actionType,
        description: description || this.getDefaultDescription(actionType),
        timestamp: Date.now()
      };
      
      this.undoStack.push(stateSnapshot);
    }
  
    /**
     * Undo last action
     */
    undo() {
      if (!this.canUndo()) {
        return null;
      }
      
      // Save current state to redo stack
      const currentSnapshot = {
        state: this.deepClone(this.currentState),
        actionType: 'REDO_POINT',
        description: 'Redo point',
        timestamp: Date.now()
      };
      this.redoStack.push(currentSnapshot);
      
      // Restore previous state
      const previousSnapshot = this.undoStack.pop();
      this.currentState = this.deepClone(previousSnapshot.state);
      
      return {
        state: this.getCurrentState(),
        undoneAction: previousSnapshot.description
      };
    }
  
    /**
     * Redo last undone action
     */
    redo() {
      if (!this.canRedo()) {
        return null;
      }
      
      // Save current state to undo stack
      this.saveToUndoStack('UNDO_POINT', 'Undo point');
      
      // Restore next state
      const nextSnapshot = this.redoStack.pop();
      this.currentState = this.deepClone(nextSnapshot.state);
      
      return {
        state: this.getCurrentState(),
        redoneAction: nextSnapshot.description
      };
    }
  
    /**
     * Check if undo is available
     */
    canUndo() {
      return this.undoStack.length > 0;
    }
  
    /**
     * Check if redo is available
     */
    canRedo() {
      return this.redoStack.length > 0;
    }
  
    /**
     * Get undo/redo status for UI
     */
    getHistoryStatus() {
      return {
        canUndo: this.canUndo(),
        canRedo: this.canRedo(),
        undoDescription: this.undoStack.length > 0 
          ? this.undoStack[this.undoStack.length - 1].description 
          : '',
        redoDescription: this.redoStack.length > 0
          ? this.redoStack[this.redoStack.length - 1].description
          : '',
        undoCount: this.undoStack.length,
        redoCount: this.redoStack.length
      };
    }
  
    /**
     * Get action history for debugging/analytics
     */
    getActionHistory() {
      return {
        undoStack: this.undoStack.map(item => ({
          actionType: item.actionType,
          description: item.description,
          timestamp: item.timestamp
        })),
        redoStack: this.redoStack.map(item => ({
          actionType: item.actionType, 
          description: item.description,
          timestamp: item.timestamp
        }))
      };
    }
  
    /**
     * Clear all history (useful for new sessions)
     */
    clearHistory() {
      this.undoStack = [];
      this.redoStack = [];
    }
  
    /**
     * Set initial state without creating history entry
     */
    setInitialState(state) {
      this.currentState = this.deepClone(state);
      this.clearHistory();
    }
  
    /**
     * Create checkpoint (useful before complex operations)
     */
    createCheckpoint(description = 'Checkpoint') {
      this.saveToUndoStack('CHECKPOINT', description);
      this.redoStack = [];
    }
  
    /**
     * Optimize memory usage by limiting stack sizes
     */
    optimizeStacks() {
      if (this.undoStack.length > this.maxHistorySize) {
        this.undoStack = this.undoStack.slice(-this.maxHistorySize);
      }
      
      if (this.redoStack.length > this.maxHistorySize) {
        this.redoStack = this.redoStack.slice(-this.maxHistorySize);
      }
    }
  
    /**
     * Get default description for action types
     */
    getDefaultDescription(actionType) {
      switch (actionType) {
        case ACTION_TYPES.ADD_WAYPOINT:
          return 'Add waypoint';
        case ACTION_TYPES.UPDATE_WAYPOINT:
          return 'Edit waypoint';
        case ACTION_TYPES.DELETE_WAYPOINT:
          return 'Delete waypoint';
        case ACTION_TYPES.MOVE_WAYPOINT:
          return 'Move waypoint';
        case ACTION_TYPES.CLEAR_TRAJECTORY:
          return 'Clear trajectory';
        case ACTION_TYPES.LOAD_TRAJECTORY:
          return 'Load trajectory';
        case ACTION_TYPES.BATCH_UPDATE:
          return 'Update trajectory';
        default:
          return 'Unknown action';
      }
    }
  
    /**
     * Deep clone object for state snapshots
     */
    deepClone(obj) {
      if (obj === null || typeof obj !== 'object') {
        return obj;
      }
      
      if (obj instanceof Date) {
        return new Date(obj.getTime());
      }
      
      if (obj instanceof Array) {
        return obj.map(item => this.deepClone(item));
      }
      
      const cloned = {};
      for (const key in obj) {
        if (obj.hasOwnProperty(key)) {
          cloned[key] = this.deepClone(obj[key]);
        }
      }
      
      return cloned;
    }
  
    /**
     * Validate state integrity
     */
    validateState(state = this.currentState) {
      const issues = [];
      
      // Check waypoints array
      if (!Array.isArray(state.waypoints)) {
        issues.push('Waypoints must be an array');
      } else {
        // Check waypoint IDs are unique
        const ids = state.waypoints.map(wp => wp.id);
        const uniqueIds = new Set(ids);
        if (ids.length !== uniqueIds.size) {
          issues.push('Waypoint IDs must be unique');
        }
        
        // Check required waypoint fields
        state.waypoints.forEach((wp, index) => {
          if (!wp.id) issues.push(`Waypoint ${index} missing ID`);
          if (typeof wp.latitude !== 'number') issues.push(`Waypoint ${index} invalid latitude`);
          if (typeof wp.longitude !== 'number') issues.push(`Waypoint ${index} invalid longitude`);
          if (typeof wp.altitude !== 'number') issues.push(`Waypoint ${index} invalid altitude`);
        });
      }
      
      // Check selected waypoint ID validity
      if (state.selectedWaypointId && state.waypoints.length > 0) {
        const hasSelected = state.waypoints.some(wp => wp.id === state.selectedWaypointId);
        if (!hasSelected) {
          issues.push('Selected waypoint ID not found in waypoints');
        }
      }
      
      return {
        valid: issues.length === 0,
        issues
      };
    }
  
    /**
     * Export state manager data for persistence
     */
    export() {
      return {
        currentState: this.getCurrentState(),
        undoStack: this.undoStack,
        redoStack: this.redoStack,
        maxHistorySize: this.maxHistorySize,
        exportedAt: Date.now()
      };
    }
  
    /**
     * Import state manager data from persistence
     */
    import(data) {
      if (!data || typeof data !== 'object') {
        throw new Error('Invalid import data');
      }
      
      this.currentState = data.currentState || { waypoints: [], selectedWaypointId: null };
      this.undoStack = data.undoStack || [];
      this.redoStack = data.redoStack || [];
      this.maxHistorySize = data.maxHistorySize || 50;
      
      // Validate imported state
      const validation = this.validateState();
      if (!validation.valid) {
        console.warn('Imported state has issues:', validation.issues);
        // Reset to safe state if validation fails
        this.setInitialState({ waypoints: [], selectedWaypointId: null });
      }
    }
  }