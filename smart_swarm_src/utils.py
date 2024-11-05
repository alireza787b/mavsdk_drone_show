# smart_swarm_src/utils.py

import math
import time
import navpy
import requests
import logging


def transform_body_to_nea(offset_forward, offset_right, yaw_deg):
    """
    Transforms body offsets (Forward, Right) to NEA (North, East) coordinates.

    Args:
        offset_forward (float): Offset in the forward direction (meters).
        offset_right (float): Offset in the right direction (meters).
        yaw_deg (float): Yaw angle in degrees.

    Returns:
        tuple: (offset_north, offset_east)
    """
    yaw_rad = math.radians(yaw_deg)
    cos_yaw = math.cos(yaw_rad)
    sin_yaw = math.sin(yaw_rad)
    offset_n = offset_forward * cos_yaw - offset_right * sin_yaw
    offset_e = offset_forward * sin_yaw + offset_right * cos_yaw
    return offset_n, offset_e

def lla_to_ned(lat, lon, alt, lat_ref, lon_ref, alt_ref):
    """
    Converts latitude, longitude, and altitude to NED coordinates relative to a reference point.

    Args:
        lat (float): Latitude in degrees.
        lon (float): Longitude in degrees.
        alt (float): Altitude in meters.
        lat_ref (float): Reference latitude in degrees.
        lon_ref (float): Reference longitude in degrees.
        alt_ref (float): Reference altitude in meters.

    Returns:
        tuple: (north, east, down) in meters
    """
    ned = navpy.lla2ned(
        lat, lon, alt,
        lat_ref, lon_ref, alt_ref,
        latlon_unit='deg', alt_unit='m', model='wgs84'
    )
    return ned[0], ned[1], -ned[2]  # navpy returns up, so we negate to get down

def ned_to_lla(north, east, down, lat_ref, lon_ref, alt_ref):
    """
    Converts NED coordinates to latitude, longitude, and altitude relative to a reference point.

    Args:
        north (float): North position in meters.
        east (float): East position in meters.
        down (float): Down position in meters.
        lat_ref (float): Reference latitude in degrees.
        lon_ref (float): Reference longitude in degrees.
        alt_ref (float): Reference altitude in meters.

    Returns:
        tuple: (latitude, longitude, altitude) in degrees and meters
    """
    lla = navpy.ned2lla(
        [north, east, -down],
        lat_ref, lon_ref, alt_ref,
        latlon_unit='deg', alt_unit='m', model='wgs84'
    )
    return lla[0], lla[1], lla[2]

def is_data_fresh(update_time, threshold):
    """
    Checks if the data is fresh based on the current time and a threshold.

    Args:
        update_time (float): The timestamp of the last data update (seconds since epoch).
        threshold (float): The freshness threshold in seconds.

    Returns:
        bool: True if data is fresh, False otherwise.
    """
    current_time = time.time()
    return (current_time - update_time) <= threshold

def get_current_timestamp():
    """
    Returns the current timestamp in seconds since the epoch.

    Returns:
        float: Current timestamp.
    """
    return time.time()



def fetch_home_position(ip, port, endpoint):
    """
    Fetches the home position from the specified endpoint.

    Args:
        ip (str): The IP address of the drone's Flask server.
        port (int): The port of the Flask server.
        endpoint (str): The endpoint to fetch the home position from.

    Returns:
        dict: A dictionary containing 'latitude', 'longitude', 'altitude', 'timestamp'.
    """
    url = f"http://{ip}:{port}/{endpoint}"
    try:
        response = requests.get(url, timeout=1)
        if response.status_code == 200:
            data = response.json()
            return data
        else:
            logging.error(f"Failed to fetch home position from {url}: HTTP {response.status_code}")
            return None
    except requests.RequestException as e:
        logging.error(f"Exception while fetching home position from {url}: {e}")
        return None
