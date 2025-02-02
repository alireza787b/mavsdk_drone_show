#!/usr/bin/env python3

import sys
import time
import logging
from rpi_ws281x import PixelStrip, Color

# Configuration for the LED (set directly in the script)
LED_PIN = 10  # GPIO pin connected to the LED strip
LED_COUNT = 25  # Number of LEDs
LED_FREQ_HZ = 800000  # LED signal frequency in Hz
LED_DMA = 10  # DMA channel
LED_BRIGHTNESS = 255  # Brightness level
LED_INVERT = False  # Whether to invert the signal
LED_CHANNEL = 0  # GPIO channel

# Define the color to set the LEDs to (red in this case)
RED_COLOR = Color(255, 0, 0)  # RGB for red

# Setup logging for error handling
logging.basicConfig(level=logging.INFO)

try:
    # Initialize the LED strip
    strip = PixelStrip(LED_COUNT, LED_PIN, freq_hz=LED_FREQ_HZ, dma=LED_DMA, invert=LED_INVERT, brightness=LED_BRIGHTNESS, channel=LED_CHANNEL)
    strip.begin()

    # Set all LEDs to red
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, RED_COLOR)
    strip.show()

    logging.info("LEDs set to red")

    # Keep the LEDs on for 5 seconds
    time.sleep(5)

    # Optionally, you can turn off the LEDs after the 5 seconds
    for i in range(strip.numPixels()):
        strip.setPixelColor(i, Color(0, 0, 0))  # Set all LEDs to off
    strip.show()

    logging.info("LEDs turned off")

except Exception as e:
    # Log any errors that occur during the process
    logging.error(f"Error initializing or controlling LEDs: {e}")
    sys.exit(0)
