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
    logger.info(f"I2C address: 0x{config.i2c_address:02x}")

    relay = RelayController(config.i2c_address, num_zones=config.num_zones)
    relay.initialize()

    controller = ValveController(relay)

    ValveRequestHandler.controller = controller

    shutting_down = False

    def shutdown_handler(signum, frame):
        nonlocal shutting_down
        if shutting_down:
            return
        shutting_down = True
        logger.info(f"Received signal {signum}, shutting down...")
        controller.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown_handler)
    signal.signal(signal.SIGINT, shutdown_handler)

    ThreadingTCPServer.allow_reuse_address = True
    # The default listen backlog (request_queue_size=5) overflows when the flaky
    # WiFi link stalls and the .101 poller piles up connections (observed SYN
    # flooding / cookies on :8686). A larger backlog lets pending requests queue
    # instead of being reset, so control commands (incl. the manager force-close)
    # are far less likely to be dropped.
    ThreadingTCPServer.request_queue_size = 128
    ThreadingTCPServer.daemon_threads = True
    server = ThreadingTCPServer(("0.0.0.0", config.port), ValveRequestHandler)

    logger.info(f"Valve Controller listening on http://0.0.0.0:{config.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if not shutting_down:
            controller.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
