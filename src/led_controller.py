# src/led_controller.py

import time
import logging
from rpi_ws281x import PixelStrip, Color
import threading
from src.params import Params

class LEDController:
    """
    LEDController is a singleton class that provides methods to control a WS2812 LED strip.
    It uses parameters defined in the Params class for configuration.
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        """
        Initialize the LEDController singleton instance. This method sets up the LED strip
        using the parameters from Params and ensures the strip is ready for operation.
        """
        if LEDController._instance is not None:
            raise Exception("This class is a singleton!")

        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        if Params.sim_mode:
            self.logger.info("Simulation mode active. LEDController will not initialize hardware.")
            self.strip = None  # No hardware initialization
            return

        # Initialize LED strip
        try:
            self.strip = PixelStrip(
                Params.led_count,
                Params.led_pin,
                Params.led_freq_hz,
                Params.led_dma,
                Params.led_invert,
                Params.led_brightness,
                Params.led_channel
            )
            self.strip.begin()
            self.logger.info("LEDController initialized with %d LEDs on GPIO pin %d", Params.led_count, Params.led_pin)
            LEDController.set_color(0,0,0) # Initialize with off LED
        except Exception as e:
            self.logger.error("Failed to initialize LEDController: %s", e)
            self.strip = None

    @staticmethod
    def get_instance():
        """
        Returns the singleton instance of LEDController. If it doesn't exist, it creates one.
        """
        if LEDController._instance is None:
            with LEDController._lock:
                if LEDController._instance is None:
                    LEDController._instance = LEDController()
        return LEDController._instance

    @staticmethod
    def set_color(r: int, g: int, b: int):
        """
        Sets all LEDs to the specified RGB color.
        """
        #in sim_mode we have no LED
        if Params.sim_mode:
            return
        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return  # Simulation mode; do nothing
            color = Color(r, g, b)
            for i in range(instance.strip.numPixels()):
                instance.strip.setPixelColor(i, color)
            instance.strip.show()
            instance.logger.debug("Set color to R:%d, G:%d, B:%d", r, g, b)

    @staticmethod
    def color_wipe(r: int, g: int, b: int, wait_ms=50):
        """
        Wipes the specified color across the LED strip one pixel at a time.
        """
        #in sim_mode we have no LED
        if Params.sim_mode:
            return
        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return  # Simulation mode; do nothing
            color = Color(r, g, b)
            for i in range(instance.strip.numPixels()):
                instance.strip.setPixelColor(i, color)
                instance.strip.show()
                time.sleep(wait_ms / 1000.0)
            instance.logger.debug("Performed color wipe with R:%d, G:%d, B:%d", r, g, b)

    @staticmethod
    def theater_chase(r: int, g: int, b: int, wait_ms=50, iterations=10):
        """
        Creates a theater chase animation with the specified color.
        """
        #in sim_mode we have no LED
        if Params.sim_mode:
            return
        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return  # Simulation mode; do nothing
            color = Color(r, g, b)
            for j in range(iterations):
                for q in range(3):
                    for i in range(0, instance.strip.numPixels(), 3):
                        instance.strip.setPixelColor(i + q, color)
                    instance.strip.show()
                    time.sleep(wait_ms / 1000.0)
                    for i in range(0, instance.strip.numPixels(), 3):
                        instance.strip.setPixelColor(i + q, 0)
                    instance.strip.show()
            instance.logger.debug("Performed theater chase with R:%d, G:%d, B:%d", r, g, b)

    @staticmethod
    def turn_off():
        """
        Turns off all LEDs.
        """
        #in sim_mode we have no LED
        if Params.sim_mode:
            return
        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return  # Simulation mode; do nothing
            for i in range(instance.strip.numPixels()):
                instance.strip.setPixelColor(i, Color(0, 0, 0))
            instance.strip.show()
            instance.logger.info("All LEDs turned off")
