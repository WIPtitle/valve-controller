import logging

logger = logging.getLogger("valve-controller")

DEVICE_BUS = 1
DEVICE_ADDR = 0x10
RELAY_ON = 0xFF
RELAY_OFF = 0x00


def build_zone_registers(num_zones: int) -> dict:
    """Generate zone register map: {"1": 1, "2": 2, ...} for num_zones zones."""
    return {str(i): i for i in range(1, num_zones + 1)}

try:
    from smbus2 import SMBus
    I2C_AVAILABLE = True
except ImportError:
    try:
        from smbus import SMBus
        I2C_AVAILABLE = True
    except ImportError:
        I2C_AVAILABLE = False
        logger.warning("smbus/smbus2 not available - running in simulation mode")


class RelayController:
    """Low-level relay hardware control via I2C (GeeekPi EP-0099)."""

    def __init__(self, i2c_address=DEVICE_ADDR, num_zones=4):
        self.i2c_address = i2c_address
        self._bus = None
        self._initialized = False
        self._zone_registers = build_zone_registers(num_zones)

    def initialize(self):
        """Open I2C bus and turn all relays OFF."""
        if not I2C_AVAILABLE:
            logger.info("Simulation mode: I2C not available")
            self._initialized = True
            return

        self._bus = SMBus(DEVICE_BUS)
        for zone, reg in self._zone_registers.items():
            self._bus.write_byte_data(self.i2c_address, reg, RELAY_OFF)
            logger.info(f"Initialized zone {zone} register 0x{reg:02x} (OFF)")

        self._initialized = True

    def set_relay(self, zone, on):
        """Turn a relay ON or OFF.
        zone: str ("1"-"4")
        on: True = relay energized (valve open), False = relay off (valve closed)
        """
        if zone not in self._zone_registers:
            raise ValueError(f"Unknown zone: {zone}")

        reg = self._zone_registers[zone]
        value = RELAY_ON if on else RELAY_OFF
        state_str = "ON" if on else "OFF"

        if not I2C_AVAILABLE or self._bus is None:
            logger.info(f"Simulation: zone {zone} reg 0x{reg:02x} -> {state_str}")
            return

        self._bus.write_byte_data(self.i2c_address, reg, value)
        logger.info(f"Zone {zone} reg 0x{reg:02x} -> {state_str}")

    def all_off(self):
        """Turn all relays OFF (safety)."""
        for zone in self._zone_registers:
            self.set_relay(zone, False)

    def cleanup(self):
        """Release I2C resources."""
        self.all_off()
        if self._bus is not None:
            self._bus.close()
            logger.info("I2C bus closed")
        self._initialized = False

    @property
    def zones(self):
        """Return list of available zone names."""
        return sorted(self._zone_registers.keys(), key=int)
