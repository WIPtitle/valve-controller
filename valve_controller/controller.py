import threading
import time
import logging
import json
import queue as queue_module

logger = logging.getLogger("valve-controller")


class ValveController:
    """Business logic: mutex, timed auto-close, occupancy state."""

    def __init__(self, relay_controller):
        self.relay = relay_controller
        self._lock = threading.Lock()
        self._active_zone = None
        self._active_timer = None
        self._open_time = None
        self._duration = None
        self._subscribers = []

    def subscribe(self):
        """Create a queue for SSE events and register it."""
        q = queue_module.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q):
        """Remove a queue from the subscriber list."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def _notify_subscribers(self, event_data: dict):
        """Push a JSON event to all subscriber queues (non-blocking)."""
        message = json.dumps(event_data)
        dead = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except queue_module.Full:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    def open_valve(self, zone, duration):
        """Open a valve for a given duration (seconds).

        Returns: (success: bool, status_code: int, message: str, detail: dict)
        """
        if zone not in self.relay.zones:
            return False, 404, "Unknown zone", {"zone": zone, "available": self.relay.zones}

        if duration <= 0:
            return False, 400, "Duration must be positive", {}

        with self._lock:
            if self._active_zone is not None:
                remaining = self._remaining_time()
                return False, 409, "Occupied", {
                    "active_zone": self._active_zone,
                    "remaining_seconds": round(remaining, 1)
                }

            self.relay.set_relay(zone, True)
            self._active_zone = zone
            self._open_time = time.monotonic()
            self._duration = duration

            self._active_timer = threading.Timer(duration, self._auto_close)
            self._active_timer.daemon = True
            self._active_timer.start()

            logger.info(f"Valve zone {zone} OPENED for {duration}s")

        self._notify_subscribers({"event": "valve_change", "zone": zone, "state": "open"})
        return True, 200, "Opened", {"zone": zone, "duration": duration}

    def close_valve(self, zone=None):
        """Close the active valve (optionally verify zone matches).

        Returns: (success: bool, status_code: int, message: str, detail: dict)
        """
        with self._lock:
            if self._active_zone is None:
                return False, 400, "No valve is currently open", {}

            if zone is not None and zone != self._active_zone:
                return False, 409, "Wrong zone", {
                    "requested_zone": zone,
                    "active_zone": self._active_zone
                }

            return self._do_close()

    def _do_close(self):
        """Internal close (must be called with lock held)."""
        zone = self._active_zone
        elapsed = time.monotonic() - self._open_time if self._open_time else 0

        if self._active_timer:
            self._active_timer.cancel()
            self._active_timer = None

        self.relay.set_relay(zone, False)
        self._active_zone = None
        self._open_time = None
        self._duration = None

        logger.info(f"Valve zone {zone} CLOSED after {elapsed:.1f}s")
        threading.Thread(
            target=self._notify_subscribers,
            args=({"event": "valve_change", "zone": zone, "state": "closed"},),
            daemon=True
        ).start()
        return True, 200, "Closed", {"zone": zone, "elapsed_seconds": round(elapsed, 1)}

    def _auto_close(self):
        """Called by timer when duration expires."""
        zone = None
        with self._lock:
            if self._active_zone is not None:
                zone = self._active_zone
                self.relay.set_relay(zone, False)
                logger.info(f"Valve zone {zone} AUTO-CLOSED (duration expired)")
                self._active_zone = None
                self._open_time = None
                self._duration = None
                self._active_timer = None
        if zone is not None:
            self._notify_subscribers({"event": "valve_change", "zone": zone, "state": "closed"})

    def get_status(self):
        """Return current state."""
        with self._lock:
            if self._active_zone is None:
                return {
                    "active": False,
                    "active_zone": None,
                    "remaining_seconds": 0,
                    "elapsed_seconds": 0,
                    "duration": 0,
                    "zones": self.relay.zones
                }
            else:
                remaining = self._remaining_time()
                elapsed = time.monotonic() - self._open_time
                return {
                    "active": True,
                    "active_zone": self._active_zone,
                    "remaining_seconds": round(remaining, 1),
                    "elapsed_seconds": round(elapsed, 1),
                    "duration": self._duration,
                    "zones": self.relay.zones
                }

    def _remaining_time(self):
        """Calculate remaining time (must be called with lock held)."""
        if self._open_time is None or self._duration is None:
            return 0
        elapsed = time.monotonic() - self._open_time
        return max(0, self._duration - elapsed)

    def shutdown(self):
        """Clean shutdown: close any active valve."""
        with self._lock:
            if self._active_zone is not None:
                self._do_close()
        self.relay.cleanup()
