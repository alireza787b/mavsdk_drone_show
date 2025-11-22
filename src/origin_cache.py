"""
Origin Caching System for Phase 2: Auto Global Origin Correction

This module provides local caching of the drone show origin coordinate system
to enable fallback operation when the GCS server is unreachable.

Features:
- Save/load origin to local JSON file
- Timestamp tracking for staleness detection
- Automatic directory creation
- Error handling for corrupted cache files

Cache file location: ~/.mavsdk_drone_show/origin_cache.json

Cache file schema:
{
    "lat": float,           # Latitude in degrees
    "lon": float,           # Longitude in degrees
    "alt": float,           # Altitude MSL in meters
    "timestamp": str,       # ISO 8601 timestamp from GCS
    "cached_at": str,       # ISO 8601 timestamp when cached locally
    "source": str           # Origin of the data: "gcs", "manual", etc.
}

Author: MAVSDK Drone Show Team
Version: 3.8 (Phase 2)
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

# Cache file location in user's home directory
CACHE_DIR = Path.home() / '.mavsdk_drone_show'
CACHE_FILE = CACHE_DIR / 'origin_cache.json'

logger = logging.getLogger(__name__)


def save_origin_to_cache(origin_data: Dict) -> bool:
    """
    Save origin coordinates to local cache file.

    Args:
        origin_data: Dictionary containing origin information
                     Required keys: lat, lon, alt
                     Optional keys: timestamp, source

    Returns:
        bool: True if save successful, False otherwise

    Example:
        >>> save_origin_to_cache({
        ...     'lat': 35.123456,
        ...     'lon': -120.654321,
        ...     'alt': 100.5,
        ...     'timestamp': '2025-11-07T12:00:00Z',
        ...     'source': 'gcs'
        ... })
        True
    """
    try:
        # Ensure cache directory exists
        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Add local caching timestamp
        origin_data['cached_at'] = datetime.utcnow().isoformat() + 'Z'

        # Write to cache file with pretty formatting
        with open(CACHE_FILE, 'w') as f:
            json.dump(origin_data, f, indent=2)

        logger.info(f"Origin cached locally: lat={origin_data['lat']:.6f}, "
                   f"lon={origin_data['lon']:.6f}, alt={origin_data['alt']:.1f}")
        return True

    except Exception as e:
        logger.error(f"Failed to save origin to cache: {e}")
        return False


def load_origin_from_cache() -> Optional[Dict]:
    """
    Load origin coordinates from local cache file.

    Returns:
        dict: Origin data if cache exists and is valid, None otherwise

    Example:
        >>> cached = load_origin_from_cache()
        >>> if cached:
        ...     print(f"Cached origin: {cached['lat']}, {cached['lon']}")
    """
    if not CACHE_FILE.exists():
        logger.debug("No origin cache file found")
        return None

    try:
        with open(CACHE_FILE, 'r') as f:
            origin_data = json.load(f)

        # Validate required fields
        required_fields = ['lat', 'lon', 'alt']
        if not all(field in origin_data for field in required_fields):
            logger.warning("Cache file missing required fields, ignoring")
            return None

        logger.debug(f"Loaded origin from cache: lat={origin_data['lat']:.6f}, "
                    f"lon={origin_data['lon']:.6f}, alt={origin_data['alt']:.1f}")
        return origin_data

    except json.JSONDecodeError as e:
        logger.error(f"Cache file corrupted (invalid JSON): {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to load origin from cache: {e}")
        return None


def get_cache_age_seconds() -> Optional[float]:
    """
    Calculate age of cached origin in seconds since it was cached locally.

    Returns:
        float: Age in seconds if cache exists, None otherwise

    Example:
        >>> age = get_cache_age_seconds()
        >>> if age and age > 3600:
        ...     print("Warning: Cache is more than 1 hour old")
    """
    cache = load_origin_from_cache()
    if not cache or 'cached_at' not in cache:
        return None

    try:
        cached_time = datetime.fromisoformat(cache['cached_at'].replace('Z', '+00:00'))
        current_time = datetime.utcnow()
        age_seconds = (current_time - cached_time.replace(tzinfo=None)).total_seconds()
        return age_seconds
    except Exception as e:
        logger.error(f"Failed to calculate cache age: {e}")
        return None


def clear_cache() -> bool:
    """
    Delete the origin cache file.

    Returns:
        bool: True if deletion successful or file doesn't exist, False on error

    Example:
        >>> clear_cache()
        True
    """
    try:
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            logger.info("Origin cache cleared")
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False


def get_cache_info() -> Dict:
    """
    Get detailed information about the cache state.

    Returns:
        dict: Cache status information including:
              - exists: bool
              - age_seconds: float or None
              - origin_data: dict or None
              - file_path: str

    Example:
        >>> info = get_cache_info()
        >>> print(f"Cache exists: {info['exists']}")
        >>> print(f"Cache age: {info['age_seconds']:.1f}s")
    """
    return {
        'exists': CACHE_FILE.exists(),
        'age_seconds': get_cache_age_seconds(),
        'origin_data': load_origin_from_cache(),
        'file_path': str(CACHE_FILE)
    }


# Example usage
if __name__ == "__main__":
    # Configure logging for standalone testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("Origin Cache System Test")
    print("=" * 50)

    # Test save
    test_origin = {
        'lat': 35.123456,
        'lon': -120.654321,
        'alt': 100.5,
        'timestamp': datetime.utcnow().isoformat() + 'Z',
        'source': 'test'
    }

    print("\n1. Saving test origin...")
    success = save_origin_to_cache(test_origin)
    print(f"   Result: {'✅ Success' if success else '❌ Failed'}")

    # Test load
    print("\n2. Loading from cache...")
    loaded = load_origin_from_cache()
    if loaded:
        print(f"   ✅ Loaded: lat={loaded['lat']:.6f}, lon={loaded['lon']:.6f}, alt={loaded['alt']:.1f}")
    else:
        print("   ❌ Failed to load")

    # Test age
    print("\n3. Checking cache age...")
    age = get_cache_age_seconds()
    if age is not None:
        print(f"   ✅ Cache age: {age:.2f} seconds")
    else:
        print("   ❌ Could not determine age")

    # Test info
    print("\n4. Cache info:")
    info = get_cache_info()
    print(f"   Exists: {info['exists']}")
    print(f"   Age: {info['age_seconds']:.2f}s" if info['age_seconds'] else "   Age: N/A")
    print(f"   Path: {info['file_path']}")

    # Test clear
    print("\n5. Clearing cache...")
    success = clear_cache()
    print(f"   Result: {'✅ Cleared' if success else '❌ Failed'}")

    print("\n" + "=" * 50)
    print("Test complete!")
