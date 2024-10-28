import requests
import logging

# Initialize logger
logger = logging.getLogger(__name__)

# Cache to store elevation data
elevation_cache = {}
RADIUS = 20 / 1000  # 20 meters in kilometers

def get_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two geographical points."""
    from math import sin, cos, sqrt, atan2, radians
    R = 6371  # Radius of the Earth in kilometers
    dLat = radians(lat2 - lat1)
    dLon = radians(lon2 - lon1)
    a = sin(dLat / 2) * sin(dLat / 2) + cos(radians(lat1)) * cos(radians(lat2)) * sin(dLon / 2) * sin(dLon / 2)
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c  # Distance in kilometers

def fetch_elevation_data(lat, lon):
    """Fetch elevation data from an external API."""
    try:
        response = requests.get(f"https://api.opentopodata.org/v1/srtm90m?locations={lat},{lon}")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error(f"Error fetching elevation data: {e}")
        return None

def get_elevation(lat, lon):
    """Get elevation data, either from cache or by fetching it."""
    # Check cache first
    for coord_key, cached_data in elevation_cache.items():
        cached_lat, cached_lon = map(float, coord_key.split(','))
        if get_distance(lat, lon, cached_lat, cached_lon) < RADIUS:
            logger.info(f"Cache hit for coordinates ({lat}, {lon})")
            return cached_data

    # Fetch from external API if not cached
    elevation_data = fetch_elevation_data(lat, lon)
    if elevation_data:
        elevation_cache[f"{lat},{lon}"] = elevation_data
        return elevation_data
    else:
        return None
