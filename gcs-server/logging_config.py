# gcs-server/logging_config.py
"""
Advanced Drone Swarm Logging System
==================================
Production-ready logging with clean terminal output, structured data,
and intelligent noise reduction for large-scale drone operations.
"""

import os
import sys
import logging
import threading
import time
import json
from datetime import datetime
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from enum import Enum
import curses
import signal

# ============================================================================
# CONFIGURATION CONSTANTS
# ============================================================================

class LogLevel(Enum):
    SILENT = 0      # Only critical errors
    QUIET = 1       # Errors and warnings only
    NORMAL = 2      # Important info + errors/warnings  
    VERBOSE = 3     # All operations
    DEBUG = 4       # Debug + all operations

class DisplayMode(Enum):
    DASHBOARD = "dashboard"    # Real-time status dashboard
    STREAM = "stream"         # Traditional log stream
    HYBRID = "hybrid"         # Dashboard + important messages

# Color schemes
class Colors:
    # Basic colors
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    
    # Status colors
    SUCCESS = "\033[92m"      # Bright green
    ERROR = "\033[91m"        # Bright red
    WARNING = "\033[93m"      # Bright yellow
    INFO = "\033[94m"         # Bright blue
    DEBUG = "\033[90m"        # Dark gray
    
    # Component colors
    DRONE = "\033[96m"        # Cyan
    SYSTEM = "\033[95m"       # Magenta
    COMMAND = "\033[97m"      # White
    
    # Status indicators
    ONLINE = "\033[92m●\033[0m"      # Green dot
    OFFLINE = "\033[91m●\033[0m"     # Red dot
    WARNING_DOT = "\033[93m●\033[0m" # Yellow dot
    UNKNOWN = "\033[90m●\033[0m"     # Gray dot

class Symbols:
    SUCCESS = "✓"
    ERROR = "✗"
    WARNING = "⚠"
    INFO = "ℹ"
    DRONE = "🛸"
    COMMAND = "⚡"
    NETWORK = "🌐"
    HEALTH = "❤"
    ARROW_RIGHT = "→"
    ARROW_UP = "↑"
    ARROW_DOWN = "↓"

# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class DroneStatus:
    """Comprehensive drone status tracking"""
    hw_id: str
    last_seen: float
    status: str = "UNKNOWN"
    telemetry_ok: bool = False
    command_ok: bool = False
    git_ok: bool = False
    network_ok: bool = False
    error_count: int = 0
    last_error: Optional[str] = None
    position: tuple = (0.0, 0.0, 0.0)
    battery: float = 0.0
    mission: str = "UNKNOWN"

@dataclass
class SystemStats:
    """System-wide statistics"""
    total_drones: int = 0
    online_drones: int = 0
    error_drones: int = 0
    commands_sent: int = 0
    commands_failed: int = 0
    uptime: float = 0.0
    start_time: float = 0.0

# ============================================================================
# CORE LOGGING MANAGER
# ============================================================================

class DroneSwarmLogger:
    """
    Centralized logging manager for drone swarm operations.
    Provides clean terminal output with intelligent noise reduction.
    """
    
    def __init__(self, log_level: LogLevel = LogLevel.NORMAL, 
                 display_mode: DisplayMode = DisplayMode.HYBRID,
                 log_file: Optional[str] = None,
                 update_interval: float = 1.0):
        
        self.log_level = log_level
        self.display_mode = display_mode
        self.update_interval = update_interval
        
        # State tracking
        self.drone_status: Dict[str, DroneStatus] = {}
        self.system_stats = SystemStats(start_time=time.time())
        self.recent_events = deque(maxlen=100)
        self.error_summary = defaultdict(int)
        
        # Thread safety
        self.lock = threading.RLock()
        self.running = True
        
        # Dashboard state
        self.last_dashboard_update = 0
        self.dashboard_lines = []
        
        # Setup logging infrastructure
        self._setup_file_logging(log_file)
        self._setup_console_logging()
        self._start_background_tasks()
        
        # Handle shutdown gracefully
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _setup_file_logging(self, log_file: Optional[str]):
        """Configure structured file logging with rotation"""
        if log_file:
            from logging.handlers import RotatingFileHandler
            
            # Ensure log directory exists
            log_dir = os.path.dirname(log_file) or "logs"
            os.makedirs(log_dir, exist_ok=True)
            
            # Setup file handler with rotation
            file_handler = RotatingFileHandler(
                log_file, maxBytes=50*1024*1024, backupCount=5
            )
            file_formatter = logging.Formatter(
                '%(asctime)s | %(levelname)-8s | %(name)-15s | %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            file_handler.setFormatter(file_formatter)
            
            # Configure root logger for file output
            root_logger = logging.getLogger()
            root_logger.setLevel(logging.DEBUG)
            root_logger.addHandler(file_handler)

    def _setup_console_logging(self):
        """Configure console logging based on display mode"""
        # Remove existing handlers to avoid conflicts
        root_logger = logging.getLogger()
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            
        # Create custom console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(self._get_logging_level())
        console_handler.setFormatter(ConsoleFormatter(self))
        
        root_logger.addHandler(console_handler)
        root_logger.setLevel(logging.DEBUG)

    def _get_logging_level(self) -> int:
        """Convert our log level to Python logging level"""
        mapping = {
            LogLevel.SILENT: logging.CRITICAL,
            LogLevel.QUIET: logging.WARNING, 
            LogLevel.NORMAL: logging.INFO,
            LogLevel.VERBOSE: logging.INFO,
            LogLevel.DEBUG: logging.DEBUG
        }
        return mapping[self.log_level]

    def _start_background_tasks(self):
        """Start background threads for dashboard updates and maintenance"""
        if self.display_mode in [DisplayMode.DASHBOARD, DisplayMode.HYBRID]:
            dashboard_thread = threading.Thread(
                target=self._dashboard_loop, daemon=True
            )
            dashboard_thread.start()
        
        # Cleanup thread
        cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True
        )
        cleanup_thread.start()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        self.running = False
        print(f"\n{Colors.INFO}Shutting down logging system...{Colors.RESET}")
        sys.exit(0)

    # ========================================================================
    # PUBLIC LOGGING INTERFACE
    # ========================================================================

    def log_drone_event(self, drone_id: str, event_type: str, 
                       message: str, level: str = "INFO", 
                       extra_data: Optional[Dict] = None):
        """Log a drone-specific event with context"""
        with self.lock:
            # Update drone status
            if drone_id not in self.drone_status:
                self.drone_status[drone_id] = DroneStatus(
                    hw_id=drone_id, last_seen=time.time()
                )
            
            drone = self.drone_status[drone_id]
            drone.last_seen = time.time()
            
            # Update specific status based on event type
            if event_type == "telemetry":
                drone.telemetry_ok = level != "ERROR"
                if extra_data:
                    drone.position = extra_data.get("position", drone.position)
                    drone.battery = extra_data.get("battery", drone.battery)
                    drone.mission = extra_data.get("mission", drone.mission)
                    drone.status = extra_data.get("status", drone.status)
            elif event_type == "command":
                drone.command_ok = level != "ERROR"
            elif event_type == "git":
                drone.git_ok = level != "ERROR"
            elif event_type == "network":
                drone.network_ok = level != "ERROR"
            
            # Track errors
            if level == "ERROR":
                drone.error_count += 1
                drone.last_error = message
                self.error_summary[f"{drone_id}:{event_type}"] += 1
                self.system_stats.commands_failed += 1
            elif event_type == "command":
                self.system_stats.commands_sent += 1
            
            # Add to recent events if important enough
            if self._should_log_event(level, event_type):
                self.recent_events.append({
                    'timestamp': time.time(),
                    'drone_id': drone_id,
                    'event_type': event_type,
                    'level': level,
                    'message': message,
                    'extra_data': extra_data
                })
                
                # Send to Python logging system
                logger = logging.getLogger(f"drone.{drone_id}.{event_type}")
                log_level = getattr(logging, level, logging.INFO)
                logger.log(log_level, message, extra={'drone_id': drone_id, 'event_type': event_type})

    def log_system_event(self, message: str, level: str = "INFO", 
                        component: str = "system", extra_data: Optional[Dict] = None):
        """Log a system-wide event"""
        with self.lock:
            if self._should_log_event(level, "system"):
                self.recent_events.append({
                    'timestamp': time.time(),
                    'drone_id': None,
                    'event_type': component,
                    'level': level,
                    'message': message,
                    'extra_data': extra_data
                })
                
                logger = logging.getLogger(f"system.{component}")
                log_level = getattr(logging, level, logging.INFO)
                logger.log(log_level, message, extra={'component': component})

    def _should_log_event(self, level: str, event_type: str) -> bool:
        """Determine if an event should be logged based on current log level"""
        if self.log_level == LogLevel.SILENT:
            return level == "CRITICAL"
        elif self.log_level == LogLevel.QUIET:
            return level in ["ERROR", "WARNING", "CRITICAL"]
        elif self.log_level == LogLevel.NORMAL:
            # Reduce telemetry noise but show important events
            if event_type == "telemetry" and level == "INFO":
                return False
            return level in ["INFO", "WARNING", "ERROR", "CRITICAL"]
        else:  # VERBOSE or DEBUG
            return True

    # ========================================================================
    # DASHBOARD IMPLEMENTATION
    # ========================================================================

    def _dashboard_loop(self):
        """Main dashboard update loop"""
        while self.running:
            try:
                if time.time() - self.last_dashboard_update > self.update_interval:
                    self._update_dashboard()
                time.sleep(0.1)
            except Exception as e:
                print(f"Dashboard error: {e}")

    def _update_dashboard(self):
        """Update the real-time dashboard display"""
        with self.lock:
            if self.display_mode == DisplayMode.STREAM:
                return
                
            # Clear screen and move cursor to top
            if self.display_mode == DisplayMode.DASHBOARD:
                print("\033[2J\033[H", end="")
            
            lines = []
            
            # System header
            uptime = time.time() - self.system_stats.start_time
            lines.extend(self._build_system_header(uptime))
            
            # Drone status overview
            lines.extend(self._build_drone_overview())
            
            # Recent events (for hybrid mode)
            if self.display_mode == DisplayMode.HYBRID:
                lines.extend(self._build_recent_events())
                
            # Error summary if there are errors
            if any(count > 0 for count in self.error_summary.values()):
                lines.extend(self._build_error_summary())
            
            # Print the dashboard
            dashboard_text = "\n".join(lines)
            if self.display_mode == DisplayMode.DASHBOARD:
                print(dashboard_text)
            elif self.display_mode == DisplayMode.HYBRID:
                # Only show dashboard periodically in hybrid mode
                if int(uptime) % 10 == 0:  # Every 10 seconds
                    print(f"\n{Colors.BOLD}=== SWARM STATUS ==={Colors.RESET}")
                    print(dashboard_text)
                    print(f"{Colors.BOLD}==================={Colors.RESET}\n")
            
            self.last_dashboard_update = time.time()

    def _build_system_header(self, uptime: float) -> List[str]:
        """Build system status header"""
        # Update system stats
        self.system_stats.total_drones = len(self.drone_status)
        self.system_stats.online_drones = sum(
            1 for d in self.drone_status.values() 
            if time.time() - d.last_seen < 30
        )
        self.system_stats.error_drones = sum(
            1 for d in self.drone_status.values() 
            if d.error_count > 0
        )
        
        uptime_str = f"{int(uptime//3600):02d}:{int((uptime%3600)//60):02d}:{int(uptime%60):02d}"
        
        lines = [
            f"{Colors.BOLD}{Colors.SYSTEM}┌─ GCS DRONE SWARM MONITOR ─────────────────────────────┐{Colors.RESET}",
            f"{Colors.SYSTEM}│ {Colors.RESET}Uptime: {Colors.BOLD}{uptime_str}{Colors.RESET} │ " +
            f"Drones: {Colors.BOLD}{self.system_stats.online_drones}/{self.system_stats.total_drones}{Colors.RESET} │ " +
            f"Errors: {Colors.ERROR if self.system_stats.error_drones > 0 else Colors.SUCCESS}{self.system_stats.error_drones}{Colors.RESET} │",
            f"{Colors.SYSTEM}│ {Colors.RESET}Commands: {Colors.BOLD}{self.system_stats.commands_sent}{Colors.RESET} │ " +
            f"Failed: {Colors.ERROR if self.system_stats.commands_failed > 0 else Colors.SUCCESS}{self.system_stats.commands_failed}{Colors.RESET} │ " +
            f"Time: {Colors.BOLD}{datetime.now().strftime('%H:%M:%S')}{Colors.RESET}{' ' * 8}│",
            f"{Colors.SYSTEM}└───────────────────────────────────────────────────────┘{Colors.RESET}",
            ""
        ]
        return lines

    def _build_drone_overview(self) -> List[str]:
        """Build drone status overview table"""
        if not self.drone_status:
            return [f"{Colors.WARNING}No drones configured{Colors.RESET}", ""]
        
        lines = [f"{Colors.BOLD}DRONE STATUS OVERVIEW{Colors.RESET}"]
        
        # Header
        header = f"{'ID':>4} │ {'Status':^8} │ {'Tel':^3} │ {'Cmd':^3} │ {'Git':^3} │ {'Net':^3} │ {'Bat':>5} │ {'Mission':^12} │ {'Errors':>6}"
        lines.append(header)
        lines.append("─" * len(header))
        
        # Sort drones by ID
        sorted_drones = sorted(self.drone_status.values(), key=lambda d: d.hw_id)
        
        for drone in sorted_drones[:20]:  # Limit to 20 for screen space
            # Determine overall status
            age = time.time() - drone.last_seen
            if age > 60:
                status_color = Colors.ERROR
                status_text = "OFFLINE"
            elif age > 30:
                status_color = Colors.WARNING
                status_text = "STALE"  
            elif drone.error_count > 5:
                status_color = Colors.ERROR
                status_text = "ERROR"
            else:
                status_color = Colors.SUCCESS
                status_text = drone.status
            
            # Status indicators
            tel_status = Colors.ONLINE if drone.telemetry_ok else Colors.OFFLINE
            cmd_status = Colors.ONLINE if drone.command_ok else Colors.OFFLINE  
            git_status = Colors.ONLINE if drone.git_ok else Colors.OFFLINE
            net_status = Colors.ONLINE if drone.network_ok else Colors.OFFLINE
            
            # Battery color coding
            if drone.battery > 50:
                bat_color = Colors.SUCCESS
            elif drone.battery > 25:
                bat_color = Colors.WARNING
            else:
                bat_color = Colors.ERROR
            
            line = (f"{Colors.DRONE}{drone.hw_id:>4}{Colors.RESET} │ "
                   f"{status_color}{status_text:^8}{Colors.RESET} │ "
                   f"{tel_status:^3} │ {cmd_status:^3} │ {git_status:^3} │ {net_status:^3} │ "
                   f"{bat_color}{drone.battery:5.1f}{Colors.RESET} │ "
                   f"{drone.mission:^12} │ "
                   f"{Colors.ERROR if drone.error_count > 0 else Colors.SUCCESS}{drone.error_count:>6}{Colors.RESET}")
            lines.append(line)
        
        if len(self.drone_status) > 20:
            lines.append(f"{Colors.DIM}... and {len(self.drone_status) - 20} more drones{Colors.RESET}")
        
        lines.append("")
        return lines

    def _build_recent_events(self) -> List[str]:
        """Build recent events log for hybrid mode"""
        lines = [f"{Colors.BOLD}RECENT EVENTS{Colors.RESET}"]
        
        # Show last 5 important events
        important_events = [
            e for e in list(self.recent_events)[-10:] 
            if e['level'] in ['WARNING', 'ERROR', 'CRITICAL'] or 
               e['event_type'] in ['command', 'system']
        ]
        
        if not important_events:
            lines.append(f"{Colors.DIM}No recent events{Colors.RESET}")
        else:
            for event in important_events[-5:]:
                timestamp = datetime.fromtimestamp(event['timestamp']).strftime('%H:%M:%S')
                level_color = getattr(Colors, event['level'], Colors.RESET)
                
                if event['drone_id']:
                    line = f"{Colors.DIM}{timestamp}{Colors.RESET} {level_color}{event['level']:>7}{Colors.RESET} {Colors.DRONE}[{event['drone_id']}]{Colors.RESET} {event['message']}"
                else:
                    line = f"{Colors.DIM}{timestamp}{Colors.RESET} {level_color}{event['level']:>7}{Colors.RESET} {Colors.SYSTEM}[SYSTEM]{Colors.RESET} {event['message']}"
                lines.append(line)
        
        lines.append("")
        return lines

    def _build_error_summary(self) -> List[str]:
        """Build error summary section"""
        lines = [f"{Colors.ERROR}ERROR SUMMARY{Colors.RESET}"]
        
        # Group errors by type
        error_types = defaultdict(int)
        for key, count in self.error_summary.items():
            if count > 0:
                _, error_type = key.split(':', 1)
                error_types[error_type] += count
        
        for error_type, count in sorted(error_types.items(), key=lambda x: x[1], reverse=True)[:5]:
            lines.append(f"  {Colors.ERROR}{error_type.upper():<12}{Colors.RESET}: {count} errors")
        
        lines.append("")
        return lines

    def _cleanup_loop(self):
        """Background cleanup of old data"""
        while self.running:
            try:
                time.sleep(60)  # Run every minute
                with self.lock:
                    # Remove stale drone entries
                    current_time = time.time()
                    stale_drones = [
                        drone_id for drone_id, drone in self.drone_status.items()
                        if current_time - drone.last_seen > 300  # 5 minutes
                    ]
                    for drone_id in stale_drones:
                        del self.drone_status[drone_id]
                    
                    # Clear old error summaries
                    if len(self.error_summary) > 1000:
                        self.error_summary.clear()
                        
            except Exception as e:
                print(f"Cleanup error: {e}")


# ============================================================================
# CUSTOM FORMATTER FOR STREAM MODE
# ============================================================================

class ConsoleFormatter(logging.Formatter):
    """Custom formatter for clean console output"""
    
    def __init__(self, logger_manager: DroneSwarmLogger):
        super().__init__()
        self.logger_manager = logger_manager

    def format(self, record: logging.LogRecord) -> str:
        """Format log record for console output"""
        # Skip if in dashboard mode (dashboard handles its own output)
        if self.logger_manager.display_mode == DisplayMode.DASHBOARD:
            return ""
        
        # Get components from logger name
        name_parts = record.name.split('.')
        component = name_parts[0] if name_parts else "system"
        
        # Color coding by level
        level_colors = {
            'DEBUG': Colors.DEBUG,
            'INFO': Colors.INFO, 
            'WARNING': Colors.WARNING,
            'ERROR': Colors.ERROR,
            'CRITICAL': Colors.ERROR + Colors.BOLD
        }
        
        level_color = level_colors.get(record.levelname, Colors.RESET)
        
        # Component colors
        component_colors = {
            'drone': Colors.DRONE,
            'system': Colors.SYSTEM,
            'command': Colors.COMMAND
        }
        component_color = component_colors.get(component, Colors.RESET)
        
        # Build formatted message
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')
        
        # Extract drone ID if available
        drone_id = getattr(record, 'drone_id', None)
        if drone_id:
            identifier = f"{component_color}[{drone_id}]{Colors.RESET}"
        else:
            identifier = f"{component_color}[{component.upper()}]{Colors.RESET}"
        
        # Symbol based on level
        symbols = {
            'DEBUG': Colors.DEBUG + Symbols.INFO + Colors.RESET,
            'INFO': Colors.INFO + Symbols.INFO + Colors.RESET,
            'WARNING': Colors.WARNING + Symbols.WARNING + Colors.RESET, 
            'ERROR': Colors.ERROR + Symbols.ERROR + Colors.RESET,
            'CRITICAL': Colors.ERROR + Colors.BOLD + Symbols.ERROR + Colors.RESET
        }
        symbol = symbols.get(record.levelname, Symbols.INFO)
        
        formatted = f"{Colors.DIM}{timestamp}{Colors.RESET} {symbol} {identifier} {record.getMessage()}"
        
        return formatted


# ============================================================================
# CONVENIENCE FUNCTIONS FOR EASY INTEGRATION
# ============================================================================

# Global logger instance
_global_logger: Optional[DroneSwarmLogger] = None

def initialize_logging(log_level: LogLevel = LogLevel.NORMAL,
                      display_mode: DisplayMode = DisplayMode.HYBRID, 
                      log_file: Optional[str] = "logs/drone_swarm.log"):
    """Initialize the global logging system"""
    global _global_logger
    
    if _global_logger is None:
        _global_logger = DroneSwarmLogger(
            log_level=log_level,
            display_mode=display_mode, 
            log_file=log_file
        )
    
    return _global_logger

def get_logger() -> DroneSwarmLogger:
    """Get the global logger instance"""
    if _global_logger is None:
        initialize_logging()
    return _global_logger

# Convenience functions for common logging operations
def log_drone_telemetry(drone_id: str, success: bool, data: Dict[str, Any]):
    """Log drone telemetry update"""
    logger = get_logger()
    level = "INFO" if success else "ERROR"
    message = "Telemetry updated" if success else "Telemetry failed"
    logger.log_drone_event(drone_id, "telemetry", message, level, data)

def log_drone_command(drone_id: str, command: str, success: bool, error: str = None):
    """Log drone command execution"""  
    logger = get_logger()
    level = "INFO" if success else "ERROR"
    message = f"Command '{command}' {'sent successfully' if success else 'failed'}"
    if error:
        message += f": {error}"
    logger.log_drone_event(drone_id, "command", message, level)

def log_system_startup(num_drones: int):
    """Log system startup"""
    logger = get_logger() 
    logger.log_system_event(
        f"GCS Server started with {num_drones} configured drones",
        "INFO", "startup"
    )

def log_system_error(message: str, component: str = "system"):
    """Log system error"""
    logger = get_logger()
    logger.log_system_event(message, "ERROR", component)

def log_system_warning(message: str, component: str = "system"):
    """Log system warning"""
    logger = get_logger()
    logger.log_system_event(message, "WARNING", component)

# Environment-based configuration
def configure_from_environment():
    """Configure logging based on environment variables"""
    # Log level
    log_level_str = os.getenv('DRONE_LOG_LEVEL', 'NORMAL').upper()
    try:
        log_level = LogLevel[log_level_str]
    except KeyError:
        log_level = LogLevel.NORMAL
    
    # Display mode
    display_mode_str = os.getenv('DRONE_DISPLAY_MODE', 'HYBRID').upper()
    try:
        display_mode = DisplayMode[display_mode_str]
    except KeyError:
        display_mode = DisplayMode.HYBRID
    
    # Log file
    log_file = os.getenv('DRONE_LOG_FILE', 'logs/drone_swarm.log')
    
    return initialize_logging(log_level, display_mode, log_file)

if __name__ == "__main__":
    # Demo/test mode
    import random
    
    print("Drone Swarm Logging System Demo")
    print("Press Ctrl+C to exit")
    
    # Initialize with dashboard mode for demo
    logger = initialize_logging(LogLevel.VERBOSE, DisplayMode.HYBRID)
    
    # Simulate drone activities
    drone_ids = [f"D{i:02d}" for i in range(1, 11)]
    
    log_system_startup(len(drone_ids))
    
    try:
        while True:
            # Simulate random events
            drone_id = random.choice(drone_ids)
            
            event_type = random.choice(['telemetry', 'command', 'git', 'network'])
            success = random.random() > 0.1  # 90% success rate
            
            if event_type == 'telemetry':
                data = {
                    'position': (random.uniform(-10, 10), random.uniform(-10, 10), random.uniform(0, 100)),
                    'battery': random.uniform(20, 100),
                    'mission': random.choice(['IDLE', 'TAKEOFF', 'MISSION', 'LAND']),
                    'status': 'ACTIVE' if success else 'ERROR'
                }
                log_drone_telemetry(drone_id, success, data)
            elif event_type == 'command':
                cmd = random.choice(['TAKEOFF', 'LAND', 'RTL', 'ARM'])
                error = None if success else "Connection timeout"
                log_drone_command(drone_id, cmd, success, error)
            else:
                level = "INFO" if success else "ERROR"
                message = f"{event_type.capitalize()} {'OK' if success else 'failed'}"
                logger.log_drone_event(drone_id, event_type, message, level)
            
            time.sleep(random.uniform(0.1, 2.0))
            
    except KeyboardInterrupt:
        print("\nDemo finished!")