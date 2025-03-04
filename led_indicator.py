#!/usr/bin/env python3
"""
LED Strip Controller for Drone Show using Raspberry Pi and rpi_ws281x library

This script initializes an LED strip and sets all LEDs to a specified color.
It is used as a visual indicator during the system startup workflow. The 
color coding is defined as follows:

    - Red: Boot has started.
    - Blue: Git synchronization is in progress.
    - Yellow/Orange: Git sync has failed after retries.
    - Green: Coordinator service is running normally.

Usage examples:
    # Set LEDs to the default color (red), indicating boot has started:
    python led_controller.py

    # Set LEDs to blue, indicating Git sync in progress:
    python led_controller.py --color blue

Author: Alireza Ghaderi
Date: 2025-03-02
"""

import sys
import logging
import argparse
from rpi_ws281x import PixelStrip, Color

# LED strip configuration constants
LED_PIN = 10          # GPIO pin connected to the LED strip
LED_COUNT = 25        # Number of LEDs in the strip
LED_FREQ_HZ = 800000  # LED signal frequency in Hz
LED_DMA = 10          # DMA channel
LED_BRIGHTNESS = 255  # Brightness level (0-255)
LED_INVERT = False    # Invert signal (True or False)
LED_CHANNEL = 0       # PWM channel

# Dictionary of predefined colors (RGB values)
# Color meanings:
#   red    : Boot has started
#   blue   : Git sync in progress
#   yellow : Git sync failed (error state)
#   green  : Coordinator running normally
#   purple, orange, white: Other optional status indicators if needed
PREDEFINED_COLORS = {
    'red': (255, 0, 0),
    'blue': (0, 0, 255),
    'green': (0, 255, 0),
    'yellow': (255, 255, 0),
    'purple': (128, 0, 128),
    'orange': (255, 165, 0),
    'white': (255, 255, 255)
}

def parse_arguments():
    """
    Parses command-line arguments.

    Returns:
        argparse.Namespace: Contains the argument 'color' (default is 'red').
    """
    parser = argparse.ArgumentParser(
        description="Control LED strip color for visual status indication."
    )
    parser.add_argument(
        '--color',
        type=str,
        default='red',
        help="Predefined color to set the LED strip. Supported colors: " +
             ", ".join(PREDEFINED_COLORS.keys()) + ". (Default: red)"
    )
    return parser.parse_args()

def get_color(color_name: str) -> Color:
    """
    Converts a predefined color name to a Color object.

    Args:
        color_name (str): Name of the color (e.g., 'red', 'blue').

    Returns:
        Color: An instance representing the LED color.

    Raises:
        ValueError: If the provided color name is not supported.
    """
    color_key = color_name.lower()
    if color_key not in PREDEFINED_COLORS:
        raise ValueError(
            f"Color '{color_name}' is not supported. Supported colors: " +
            ", ".join(PREDEFINED_COLORS.keys())
        )
    r, g, b = PREDEFINED_COLORS[color_key]
    return Color(r, g, b)

def initialize_strip() -> PixelStrip:
    """
    Initializes and returns the LED strip object.

    Returns:
        PixelStrip: An initialized LED strip.
    """
    strip = PixelStrip(
        LED_COUNT,
        LED_PIN,
        freq_hz=LED_FREQ_HZ,
        dma=LED_DMA,
        invert=LED_INVERT,
        brightness=LED_BRIGHTNESS,
        channel=LED_CHANNEL
    )
    strip.begin()
    return strip

def set_strip_color(strip: PixelStrip, color: Color):
    """
    Sets all LEDs on the strip to the specified color.

    Args:
        strip (PixelStrip): The LED strip object.
        color (Color): The color to set on all LEDs.
    """
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, color)
    strip.show()

def main():
    """
    Main function to parse arguments, initialize the LED strip, and set its color.
    Also logs the meaning of the selected color for troubleshooting.
    """
    # Configure logging to output informational messages with timestamps
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Parse command-line arguments
    args = parse_arguments()

    try:
        # Get the LED color from the provided argument
        led_color = get_color(args.color)
    except ValueError as error:
        logging.error(error)
        sys.exit(1)

    # Log the meaning of the color being set
    color_meanings = {
        'red': "Boot has started.",
        'blue': "Git sync in progress.",
        'yellow': "Git sync failed.",
        'green': "Coordinator service running normally.",
        'purple': "Optional status indicator.",
        'orange': "Optional status indicator.",
        'white': "Optional status indicator."
    }
    meaning = color_meanings.get(args.color.lower(), "No defined meaning.")
    logging.info(f"Setting LED color to {args.color} - {meaning}")

    try:
        # Initialize the LED strip
        strip = initialize_strip()
        # Set all LEDs to the specified color
        set_strip_color(strip, led_color)
        logging.info(f"LEDs successfully set to {args.color}.")
    except Exception as e:
        logging.error(f"Error initializing or controlling LEDs: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
