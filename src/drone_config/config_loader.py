# src/drone_config/config_loader.py
"""
Configuration Loader
====================
Static utilities for loading drone configuration from files and network.

This module provides stateless methods for:
- Reading hardware ID from MDS runtime env or .hwID files
- Loading config.json and swarm.json files
- Fetching online configurations
- Loading trajectory-based drone positions
"""

import csv
import glob
import logging
import os
from typing import Dict, Optional, Any

import requests

from src.params import Params

logger = logging.getLogger(__name__)


class ConfigLoader:
    """
    Static utilities for loading drone configuration data.

    TODO(deferred): Central config service (pull-based).
    Drones pull config from GCS API on boot instead of reading local JSON.
    See docs/TODO_deferred.md #4

    All methods are class methods that don't require instance state,
    making them easy to test and use independently.
    """

    @staticmethod
    def _extract_entries(data: Any, filename: str) -> Any:
        """
        Extract wrapped config entries from JSON payloads.

        Supports both fleet wrappers (`{"drones": [...]}`) and swarm wrappers
        (`{"assignments": [...]}`), while remaining backward compatible with
        legacy raw lists.
        """
        if isinstance(data, dict):
            if 'drones' in data:
                return data['drones']
            if 'assignments' in data:
                return data['assignments']
            raise ValueError(
                f"Unsupported JSON structure in {filename}. "
                "Expected 'drones' or 'assignments' wrapper."
            )
        return data

    @staticmethod
    def get_hw_id(hw_id: Optional[int] = None) -> Optional[int]:
        """
        Retrieve the hardware ID from provided value, MDS runtime env, or
        a discovered `.hwID` file.

        Args:
            hw_id: Optional hardware ID (int). If provided, returned as-is.

        Returns:
            Hardware ID as int, or None if not found.
        """
        if hw_id is not None:
            try:
                return int(hw_id)
            except (ValueError, TypeError):
                logger.error(f"Provided hw_id is not a valid integer: {hw_id}")
                return None

        env_hw_id = os.environ.get("MDS_HW_ID")
        if env_hw_id:
            try:
                resolved_hw_id = int(env_hw_id)
                logger.info(f"Hardware ID loaded from MDS_HW_ID: {resolved_hw_id}")
                return resolved_hw_id
            except ValueError:
                logger.error(f"MDS_HW_ID is not a valid integer: {env_hw_id}")

        search_dirs = []
        for directory in (
            os.environ.get("MDS_HWID_DIR"),
            os.getcwd(),
            os.environ.get("MDS_BASE_DIR"),
            os.path.expanduser("~/mavsdk_drone_show"),
        ):
            if directory and directory not in search_dirs:
                search_dirs.append(directory)

        searched_patterns = []
        for directory in search_dirs:
            pattern = os.path.join(directory, "*.hwID")
            searched_patterns.append(pattern)
            hw_id_files = sorted(glob.glob(pattern))
            if hw_id_files:
                hw_id_file = hw_id_files[0]
                logger.info(f"Hardware ID file found: {hw_id_file}")
                try:
                    resolved_hw_id = int(os.path.basename(hw_id_file).split(".")[0])
                except ValueError:
                    logger.error(f"Hardware ID filename is not a valid integer: {hw_id_file}")
                    return None
                logger.info(f"Hardware ID: {resolved_hw_id}")
                return resolved_hw_id

        logger.error(
            "Hardware ID file not found. Checked MDS_HW_ID and patterns: %s",
            ", ".join(searched_patterns) if searched_patterns else "<none>",
        )
        return None

    @staticmethod
    def read_file(filename: str, source: str, hw_id: int) -> Optional[Dict[str, Any]]:
        """
        Read a JSON configuration file and return the entry matching hw_id.

        Args:
            filename: Path to JSON file
            source: Description of file source (for logging)
            hw_id: Hardware ID (int) to find in JSON

        Returns:
            Dictionary with configuration data, or None if not found.
        """
        try:
            import json
            with open(filename, 'r') as f:
                data = json.load(f)
            entries = ConfigLoader._extract_entries(data, filename)
            if not isinstance(entries, list):
                raise ValueError(f"Expected a list of entries in {filename}")
            for entry in entries:
                if int(entry.get('hw_id', -1)) == hw_id:
                    logger.debug(f"Configuration for HW_ID {hw_id} found in {source}.")
                    return dict(entry)
            logger.warning(f"hw_id {hw_id} not found in {filename}")
            return None
        except FileNotFoundError:
            logger.error(f"File not found: {filename}")
        except Exception as e:
            logger.error(f"Error reading {source} ({filename}): {e}")
        return None

    @staticmethod
    def fetch_online_config(url: str, local_filename: str, hw_id: int) -> Optional[Dict[str, Any]]:
        """
        Fetch configuration from online source and save locally.

        Args:
            url: URL to fetch configuration from
            local_filename: Local file path to save fetched config
            hw_id: Hardware ID (int) to find in fetched config

        Returns:
            Dictionary with configuration data, or None if fetch failed.
        """
        logger.info(f"Loading configuration from {url}...")
        try:
            response = requests.get(url)

            if response.status_code != 200:
                logger.error(f'Error downloading file: {response.status_code} {response.reason}')
                return None

            with open(local_filename, 'w') as f:
                f.write(response.text)

            return ConfigLoader.read_file(local_filename, 'online config', hw_id)

        except Exception as e:
            logger.error(f"Failed to load online configuration: {e}")
            return None

    @staticmethod
    def read_config(hw_id: int) -> Optional[Dict[str, Any]]:
        """
        Read configuration from local JSON file or online source.

        Defaults to local file mode. Remote fetch is only used when
        MDS_LOCAL_CONFIG_MODE=false and MDS_CONFIG_URL is explicitly set.

        Args:
            hw_id: Hardware ID (int) to load config for

        Returns:
            Dictionary with configuration data, or None if not found.
        """
        if Params.offline_config or not Params.config_url:
            return ConfigLoader.read_file(Params.config_file_name, 'local config', hw_id)
        return ConfigLoader.fetch_online_config(Params.config_url, 'online_config.json', hw_id)

    @staticmethod
    def read_swarm(hw_id: int) -> Optional[Dict[str, Any]]:
        """
        Read swarm configuration from local JSON file or online source.

        Defaults to local file mode. Remote fetch is only used when
        MDS_LOCAL_SWARM_MODE=false and MDS_SWARM_URL is explicitly set.

        Args:
            hw_id: Hardware ID (int) to load swarm config for

        Returns:
            Dictionary with swarm configuration data, or None if not found.
        """
        if Params.offline_swarm or not Params.swarm_url:
            return ConfigLoader.read_file(Params.swarm_file_name, 'local config', hw_id)
        return ConfigLoader.fetch_online_config(Params.swarm_url, 'online_swarm.json', hw_id)

    @staticmethod
    def load_all_configs() -> Dict[int, Dict[str, float]]:
        """
        Load all drone configurations from config.json and trajectory files.

        Reads pos_ids from config.json, then loads x,y positions from
        corresponding trajectory CSV files (single source of truth).

        Returns:
            Dictionary mapping pos_id to {x, y} position data.
        """
        import json
        all_configs: Dict[int, Dict[str, float]] = {}
        try:
            with open(Params.config_file_name, 'r') as f:
                data = json.load(f)
            entries = data.get('drones', data) if isinstance(data, dict) else data
            for entry in entries:
                pos_id = int(entry['pos_id'])

                # Get position from trajectory CSV (single source of truth)
                base_dir = 'shapes_sitl' if Params.sim_mode else 'shapes'

                # Navigate from src/drone_config/ to project root
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
                trajectory_file = os.path.join(
                    project_root,
                    base_dir,
                    'swarm',
                    'processed',
                    f"Drone {pos_id}.csv"
                )

                try:
                    if os.path.exists(trajectory_file):
                        with open(trajectory_file, 'r') as traj_f:
                            traj_reader = csv.DictReader(traj_f)  # Trajectory stays CSV!
                            first_waypoint = next(traj_reader, None)
                            if first_waypoint:
                                x = float(first_waypoint.get('px', 0))  # North
                                y = float(first_waypoint.get('py', 0))  # East
                                all_configs[pos_id] = {'x': x, 'y': y}
                            else:
                                logger.warning(f"Trajectory file empty for pos_id={pos_id}")
                                all_configs[pos_id] = {'x': 0, 'y': 0}
                    else:
                        logger.warning(f"Trajectory file not found for pos_id={pos_id}: {trajectory_file}")
                        all_configs[pos_id] = {'x': 0, 'y': 0}
                except Exception as e:
                    logger.error(f"Error reading trajectory for pos_id={pos_id}: {e}")
                    all_configs[pos_id] = {'x': 0, 'y': 0}

            logger.info("All drone configurations loaded from config and trajectory files.")
        except FileNotFoundError:
            logger.error(f"Config file {Params.config_file_name} not found.")
        except Exception as e:
            logger.error(f"Error loading all drone configurations: {e}")
        return all_configs
