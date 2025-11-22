# src/led_controller.py

import time
import logging
import threading
from src.params import Params

# ===================================================================================
# LED LIBRARY IMPORTS - SAFE FAILOVER APPROACH
# ===================================================================================
#
# Current approach: Try Pi 4 method (rpi_ws281x) first, fallback to Pi 5 (Pi5Neo)
# This ensures backward compatibility while supporting new hardware.
#
# TODO (Future Production): Implement board-specific configuration system
#   - Add board detection module (Pi 4, Pi 5, Jetson, etc.)
#   - Move LED config to per-board profiles in params.py
#   - Support multiple LED controllers (WS2812, APA102, etc.)
#   - Add board capability detection and validation
#   - See: https://github.com/alireza787b/mavsdk_drone_show/issues/XXX
#
# ===================================================================================

LED_LIBRARY = None
PixelStrip = None
Color = None
Pi5Neo = None

# Try Raspberry Pi 4 library first (default, proven method)
try:
    from rpi_ws281x import PixelStrip, Color
    LED_LIBRARY = 'rpi_ws281x'
    print("[LED] Loaded rpi_ws281x library (Pi 4 default)")
except ImportError:
    print("[LED] rpi_ws281x not available, trying Pi5Neo...")
    # Fallback to Raspberry Pi 5 library
    try:
        from Pi5Neo import Pi5Neo
        LED_LIBRARY = 'Pi5Neo'
        print("[LED] Loaded Pi5Neo library (Pi 5 fallback)")
    except ImportError:
        LED_LIBRARY = None
        print("[LED] WARNING: No LED library available - LED support disabled")
        print("[LED] Install: pip install rpi-ws281x (Pi 4) OR pip install Pi5Neo (Pi 5)")


class LEDController:
    """
    LEDController is a singleton class that provides methods to control a WS2812 LED strip.

    Supports multiple hardware platforms with automatic fallback:
      - Raspberry Pi 4/3/2: rpi_ws281x library (PWM/DMA-based)
      - Raspberry Pi 5: Pi5Neo library (SPI-based)
      - Future: TODO - Add Jetson, custom boards via config system

    Hardware Connections:
      - GPIO 10 (SPI0 MOSI) - Works on all Pi models

    Safety:
      - Never crashes main system if LED hardware fails
      - Gracefully degrades to no-LED operation
      - All methods wrapped in try-except for robustness
    """
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        """
        Initialize the LEDController singleton instance.

        Uses safe failover approach:
        1. Try rpi_ws281x (Pi 4 default)
        2. If fails, try Pi5Neo (Pi 5 fallback)
        3. If both fail, disable LEDs gracefully
        """
        if LEDController._instance is not None:
            raise Exception("This class is a singleton!")

        # Setup logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)

        self.strip = None
        self.led_library = None

        # Skip hardware initialization in simulation mode
        if Params.sim_mode:
            self.logger.info("Simulation mode active. LEDController will not initialize hardware.")
            return

        # Check if any LED library is available
        if LED_LIBRARY is None:
            self.logger.warning("No LED library available - LED support disabled")
            self.logger.warning("System will continue normally without LED feedback")
            return

        # Initialize LED strip with safe failover approach
        # TODO (Future): Replace with board-specific config from params.py
        try:
            if LED_LIBRARY == 'rpi_ws281x':
                # Method 1: Raspberry Pi 4 (default, proven)
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
                    self.led_library = 'rpi_ws281x'
                    self.logger.info(
                        f"LEDController initialized: {Params.led_count} LEDs on GPIO {Params.led_pin} "
                        f"using rpi_ws281x (Pi 4 method)"
                    )
                except Exception as e:
                    self.logger.warning(f"rpi_ws281x initialization failed: {e}")
                    # Don't raise - try Pi5Neo as emergency fallback
                    if LED_LIBRARY == 'rpi_ws281x':
                        try:
                            # Emergency fallback: Import and use Pi5Neo
                            from Pi5Neo import Pi5Neo
                            self.logger.info("Attempting Pi5Neo as emergency fallback...")
                            # Pi5Neo constructor: Pi5Neo(spi_device, num_leds, spi_speed_khz)
                            self.strip = Pi5Neo(
                                '/dev/spidev0.0',
                                Params.led_count,
                                800  # SPI speed in kHz (not brightness!)
                            )
                            self.led_library = 'Pi5Neo'
                            self.logger.info(
                                f"✅ LEDController initialized: {Params.led_count} LEDs on SPI0 "
                                f"using Pi5Neo (emergency fallback from Pi 4)"
                            )
                        except Exception as e2:
                            self.logger.error(f"Emergency Pi5Neo fallback also failed: {e2}")
                            self.logger.warning("LED support disabled - system will continue normally")
                            self.strip = None

            elif LED_LIBRARY == 'Pi5Neo':
                # Method 2: Raspberry Pi 5 (SPI-based)
                # Pi5Neo constructor: Pi5Neo(spi_device, num_leds, spi_speed_khz)
                self.strip = Pi5Neo(
                    '/dev/spidev0.0',
                    Params.led_count,
                    800  # SPI speed in kHz (WS2812 standard frequency)
                )
                self.led_library = 'Pi5Neo'
                self.logger.info(
                    f"✅ LEDController initialized: {Params.led_count} LEDs on SPI0 "
                    f"using Pi5Neo (Pi 5 direct)"
                )

        except Exception as e:
            # Safe degradation: Disable LEDs but don't crash system
            self.logger.error(f"LED initialization failed: {e}")
            self.logger.warning("Continuing without LED support - system will function normally")
            self.strip = None
            self.led_library = None

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
        RGB values are clamped to 0-255 range and converted to integers for robustness.

        Args:
            r: Red component (0-255, will be clamped)
            g: Green component (0-255, will be clamped)
            b: Blue component (0-255, will be clamped)

        Safety:
            Never crashes - returns silently if LED hardware unavailable
        """
        # Skip in sim_mode
        if Params.sim_mode:
            return

        # Robust value clamping and type conversion
        try:
            r = int(max(0, min(255, float(r))))
            g = int(max(0, min(255, float(g))))
            b = int(max(0, min(255, float(b))))
        except (ValueError, TypeError) as e:
            # Safe fallback to black
            instance = LEDController.get_instance()
            instance.logger.warning(f"LED color conversion error: {e}, using safe defaults (0,0,0)")
            r, g, b = 0, 0, 0

        with LEDController._lock:
            instance = LEDController.get_instance()

            # Safe return if no LED hardware
            if instance.strip is None:
                return

            # Set LED colors with library-specific API
            # TODO (Future): Abstract this with LED driver interface class
            try:
                if instance.led_library == 'Pi5Neo':
                    # Pi 5: Use Pi5Neo API
                    for i in range(Params.led_count):
                        instance.strip.set_led_color(i, r, g, b)
                    instance.strip.update_strip()

                elif instance.led_library == 'rpi_ws281x':
                    # Pi 4 and earlier: Use rpi_ws281x API
                    color = Color(r, g, b)
                    for i in range(instance.strip.numPixels()):
                        instance.strip.setPixelColor(i, color)
                    instance.strip.show()

                instance.logger.debug("Set color to R:%d, G:%d, B:%d", r, g, b)

            except Exception as e:
                # Never crash - just log error
                instance.logger.error(f"Error setting LED color: {e}")

    @staticmethod
    def color_wipe(r: int, g: int, b: int, wait_ms=50):
        """
        Wipes the specified color across the LED strip one pixel at a time.

        Safety: Never crashes - returns silently if LED hardware unavailable
        """
        if Params.sim_mode:
            return

        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return

            try:
                r = int(max(0, min(255, float(r))))
                g = int(max(0, min(255, float(g))))
                b = int(max(0, min(255, float(b))))

                # TODO (Future): Abstract LED operations with driver interface
                if instance.led_library == 'Pi5Neo':
                    for i in range(Params.led_count):
                        instance.strip.set_led_color(i, r, g, b)
                        instance.strip.update_strip()
                        time.sleep(wait_ms / 1000.0)

                elif instance.led_library == 'rpi_ws281x':
                    color = Color(r, g, b)
                    for i in range(instance.strip.numPixels()):
                        instance.strip.setPixelColor(i, color)
                        instance.strip.show()
                        time.sleep(wait_ms / 1000.0)

                instance.logger.debug("Performed color wipe with R:%d, G:%d, B:%d", r, g, b)

            except Exception as e:
                instance.logger.error(f"Error in color_wipe: {e}")

    @staticmethod
    def theater_chase(r: int, g: int, b: int, wait_ms=50, iterations=10):
        """
        Creates a theater chase animation with the specified color.

        Safety: Never crashes - returns silently if LED hardware unavailable
        """
        if Params.sim_mode:
            return

        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return

            try:
                r = int(max(0, min(255, float(r))))
                g = int(max(0, min(255, float(g))))
                b = int(max(0, min(255, float(b))))

                # TODO (Future): Abstract LED operations with driver interface
                if instance.led_library == 'Pi5Neo':
                    for j in range(iterations):
                        for q in range(3):
                            for i in range(0, Params.led_count, 3):
                                instance.strip.set_led_color(i + q, r, g, b)
                            instance.strip.update_strip()
                            time.sleep(wait_ms / 1000.0)
                            for i in range(0, Params.led_count, 3):
                                instance.strip.set_led_color(i + q, 0, 0, 0)
                            instance.strip.update_strip()

                elif instance.led_library == 'rpi_ws281x':
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

            except Exception as e:
                instance.logger.error(f"Error in theater_chase: {e}")

    @staticmethod
    def turn_off():
        """
        Turns off all LEDs.

        Safety: Never crashes - returns silently if LED hardware unavailable
        """
        if Params.sim_mode:
            return

        with LEDController._lock:
            instance = LEDController.get_instance()
            if instance.strip is None:
                return

            try:
                # TODO (Future): Abstract LED operations with driver interface
                if instance.led_library == 'Pi5Neo':
                    for i in range(Params.led_count):
                        instance.strip.set_led_color(i, 0, 0, 0)
                    instance.strip.update_strip()

                elif instance.led_library == 'rpi_ws281x':
                    for i in range(instance.strip.numPixels()):
                        instance.strip.setPixelColor(i, Color(0, 0, 0))
                    instance.strip.show()

                instance.logger.info("All LEDs turned off")

            except Exception as e:
                instance.logger.error(f"Error turning off LEDs: {e}")
