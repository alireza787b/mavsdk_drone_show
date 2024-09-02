import time
import logging
from src.led_controller import LEDController

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_tests():
    logger.info("Starting LEDController tests...")

    # Initialize LEDController (this happens automatically)
    led_controller = LEDController.get_instance()

    # Test: Set colors
    logger.info("Test: Set color to Red")
    LEDController.set_color(255, 0, 0)
    time.sleep(2)

    logger.info("Test: Set color to Green")
    LEDController.set_color(0, 255, 0)
    time.sleep(2)

    logger.info("Test: Set color to Blue")
    LEDController.set_color(0, 0, 255)
    time.sleep(2)

    logger.info("Test: Set color to Yellow (Red + Green)")
    LEDController.set_color(255, 255, 0)
    time.sleep(2)

    logger.info("Test: Set color to Cyan (Green + Blue)")
    LEDController.set_color(0, 255, 255)
    time.sleep(2)

    logger.info("Test: Set color to Magenta (Red + Blue)")
    LEDController.set_color(255, 0, 255)
    time.sleep(2)

    logger.info("Test: Set color to White (Red + Green + Blue)")
    LEDController.set_color(255, 255, 255)
    time.sleep(2)

    # Test: Blinking
    logger.info("Test: Blink Red 3 times")
    for _ in range(3):
        LEDController.set_color(255, 0, 0)
        time.sleep(0.5)
        LEDController.turn_off()
        time.sleep(0.5)

    logger.info("Test: Blink Green 3 times")
    for _ in range(3):
        LEDController.set_color(0, 255, 0)
        time.sleep(0.5)
        LEDController.turn_off()
        time.sleep(0.5)

    logger.info("Test: Blink Blue 3 times")
    for _ in range(3):
        LEDController.set_color(0, 0, 255)
        time.sleep(0.5)
        LEDController.turn_off()
        time.sleep(0.5)

    # Test: Patterns
    logger.info("Test: Running color wipe (Red)")
    LEDController.color_wipe(255, 0, 0, wait_ms=100)

    logger.info("Test: Running color wipe (Green)")
    LEDController.color_wipe(0, 255, 0, wait_ms=100)

    logger.info("Test: Running color wipe (Blue)")
    LEDController.color_wipe(0, 0, 255, wait_ms=100)

    logger.info("Test: Running theater chase (Red)")
    LEDController.theater_chase(255, 0, 0, wait_ms=100)

    logger.info("Test: Running theater chase (Green)")
    LEDController.theater_chase(0, 255, 0, wait_ms=100)

    logger.info("Test: Running theater chase (Blue)")
    LEDController.theater_chase(0, 0, 255, wait_ms=100)

    # Turn off LEDs
    logger.info("Test: Turning off all LEDs")
    LEDController.turn_off()

    logger.info("LEDController tests completed.")

if __name__ == "__main__":
    run_tests()
