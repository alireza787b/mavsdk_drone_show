#!/usr/bin/env python3

import sys
import logging

# Add error handling and logging to ensure failure does not block the process
try:
    # Import the LEDController from your project
    from src.led_controller import LEDController
    
    # Attempt to initialize the LED and set the color to red
    LEDController.set_color(255, 0, 0)  # Red color

    # Optional: Let the LED stay on for 5 seconds as an indication
    import time
    time.sleep(5)

except Exception as e:
    # Log the error if the LED setup fails (i.e., any issues with hardware, library, etc.)
    logging.basicConfig(level=logging.ERROR)
    logging.error(f"Failed to initialize LED or set color: {e}")

    # Skip and proceed without stopping the rest of the system
    sys.exit(0)
