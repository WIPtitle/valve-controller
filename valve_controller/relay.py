import logging

logger = logging.getLogger("valve-controller")

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except (ImportError, RuntimeError):
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available - running in simulation mode")


class RelayController:
    """Low-level relay hardware control via GPIO."""

    def __init__(self, relay_pins, active_low=True):
        """
        relay_pins: dict mapping zone str ("1"-"4") to BCM GPIO pin number
        active_low: if True, LOW=relay ON, HIGH=relay OFF
        """
        self.relay_pins = {str(k): int(v) for k, v in relay_pins.items()}
        self.active_low = active_low
        self._initialized = False

    def initialize(self):
        """Set up GPIO pins as outputs, all relays OFF."""
        if not GPIO_AVAILABLE:
            logger.info("Simulation mode: GPIO not initialized")
            self._initialized = True
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        off_state = GPIO.HIGH if self.active_low else GPIO.LOW
        for zone, pin in self.relay_pins.items():
            GPIO.setup(pin, GPIO.OUT, initial=off_state)
            logger.info(f"Initialized zone {zone} on GPIO {pin} (OFF)")

        self._initialized = True

    def set_relay(self, zone, on):
        """Turn a relay ON or OFF.
        zone: str ("1"-"4")
        on: True = relay energized (valve open), False = relay off (valve closed)
        """
        if zone not in self.relay_pins:
            raise ValueError(f"Unknown zone: {zone}")

        pin = self.relay_pins[zone]

        if not GPIO_AVAILABLE:
            state_str = "ON" if on else "OFF"
            logger.info(f"Simulation: zone {zone} GPIO {pin} -> {state_str}")
            return

        if on:
            level = GPIO.LOW if self.active_low else GPIO.HIGH
        else:
            level = GPIO.HIGH if self.active_low else GPIO.LOW

        GPIO.output(pin, level)
        state_str = "ON" if on else "OFF"
        logger.info(f"Zone {zone} GPIO {pin} -> {state_str}")

    def all_off(self):
        """Turn all relays OFF (safety)."""
        for zone in self.relay_pins:
            self.set_relay(zone, False)

    def cleanup(self):
        """Release GPIO resources."""
        self.all_off()
        if GPIO_AVAILABLE:
            GPIO.cleanup()
            logger.info("GPIO cleanup complete")
        self._initialized = False

    @property
    def zones(self):
        """Return list of available zone names."""
        return sorted(self.relay_pins.keys())
