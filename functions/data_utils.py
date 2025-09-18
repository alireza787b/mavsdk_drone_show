import logging


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (ValueError, TypeError) as e:
        logging.debug(f"Error converting value to int: {e}. Using default {default}.")
        return default

def safe_float(value, default=0.0):
    try:
        if value is None:
            logging.warning(f"Expected float, got None. Using default {default}.")
            return default
        return float(value)
    except (ValueError, TypeError) as e:
        logging.error(f"Error converting value to float: {e}. Using default {default}.")
        return default

# Safely get nested values and handle if dict or key does not exist
def safe_get(dct, key, default=None):
    try:
        if dct is None or key not in dct:
            logging.warning(f"Key '{key}' missing in dict or dict is None. Using default {default}.")
            return default
        return dct[key]
    except (AttributeError, TypeError) as e:
        logging.error(f"Error accessing key '{key}' in dict: {e}. Using default {default}.")
        return default