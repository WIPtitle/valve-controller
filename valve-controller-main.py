#!/usr/bin/env python3
"""Valve Controller Server - controls solenoid valves via relay board."""

import signal
import sys
import logging
from socketserver import ThreadingTCPServer
from valve_controller import ConfigManager, RelayController, ValveController, ValveRequestHandler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger("valve-controller")


def main():
    config = ConfigManager()
    logger.info(f"Starting Valve Controller on port {config.port}")
    logger.info(f"Relay pins: {config.relay_pins}")
    logger.info(f"Active low: {config.active_low}")

    relay = RelayController(config.relay_pins, config.active_low)
    relay.initialize()

    controller = ValveController(relay)

    ValveRequestHandler.controller = controller

    def shutdown_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        controller.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    server = ThreadingTCPServer(("0.0.0.0", config.port), ValveRequestHandler)
    server.allow_reuse_address = True

    logger.info(f"Valve Controller listening on http://0.0.0.0:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        controller.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
