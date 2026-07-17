import threading
import time
import logging
import json
import queue as queue_module

logger = logging.getLogger("valve-controller")

# Hard safety ceiling: a valve is NEVER allowed to stay open longer than this,
# whatever duration is requested. Scheduled runs are minutes; manual opens ~10min.
MAX_DURATION_SECONDS = 1800  # 30 minutes

# How often the auto-close watchdog re-checks (seconds).
_WATCHDOG_TICK = 0.5
# Retries when physically switching a relay OFF fails (flaky I2C bus).
_OFF_RETRIES = 5
_OFF_RETRY_DELAY = 0.5


class ValveController:
    """Business logic: mutex, timed auto-close, occupancy state.

    Timing is deliberately based ONLY on the monotonic clock (time.monotonic)
    and monotonic-relative sleeps (time.sleep). It never reads the wall clock
    (time.time), because this device has no RTC and its wall clock jumps/steps
    arbitrarily. A wall-clock step must never delay a valve's auto-close.
    """

    def __init__(self, relay_controller):
        self.relay = relay_controller
        self._lock = threading.Lock()
        self._active_zone = None
        self._open_monotonic = None      # time.monotonic() at open — NEVER time.time()
        self._duration = None
        self._cancel = None              # threading.Event: signals the watchdog to stop
        self._watchdog = None
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

        try:
            duration = float(duration)
        except (TypeError, ValueError):
            return False, 400, "Invalid duration", {}
        if duration <= 0:
            return False, 400, "Duration must be positive", {}

        # Clamp to the hard safety ceiling.
        if duration > MAX_DURATION_SECONDS:
            logger.warning(
                f"Requested duration {duration}s exceeds cap {MAX_DURATION_SECONDS}s — clamping"
            )
            duration = MAX_DURATION_SECONDS

        with self._lock:
            if self._active_zone is not None:
                remaining = self._remaining_time()
                return False, 409, "Occupied", {
                    "active_zone": self._active_zone,
                    "remaining_seconds": round(remaining, 1)
                }

            try:
                self.relay.set_relay(zone, True)
            except Exception as e:
                logger.error(f"Failed to energize relay for zone {zone}: {e}")
                # Best effort: make sure nothing is left partially energized.
                try:
                    self.relay.set_relay(zone, False)
                except Exception:
                    pass
                return False, 500, "Relay error", {"zone": zone, "error": str(e)}

            self._active_zone = zone
            self._open_monotonic = time.monotonic()
            self._duration = duration
            self._cancel = threading.Event()
            self._watchdog = threading.Thread(
                target=self._auto_close_watchdog,
                args=(zone, duration, self._cancel),
                daemon=True,
            )
            self._watchdog.start()

            logger.info(f"Valve zone {zone} OPENED for {duration}s")

        self._notify_subscribers({"event": "valve_change", "zone": zone, "state": "open"})
        return True, 200, "Opened", {"zone": zone, "duration": duration}

    def _auto_close_watchdog(self, zone, duration, cancel):
        """Count down `duration` in REAL time and auto-close, regardless of the
        system wall clock.

        Elapsed is measured as max(monotonic delta, accumulated sleep time).
        time.sleep() is a CLOCK_MONOTONIC-relative sleep on Linux, so it advances
        with real time even if the wall clock (or absolute monotonic value) is
        misbehaving. Whichever measure reaches `duration` first triggers the
        close — the safe direction (never stays open too long).
        """
        start = time.monotonic()
        slept = 0.0
        while not cancel.is_set():
            elapsed = max(time.monotonic() - start, slept)
            remaining = duration - elapsed
            if remaining <= 0:
                break
            nap = _WATCHDOG_TICK if remaining > _WATCHDOG_TICK else remaining
            time.sleep(nap)
            slept += nap
        if cancel.is_set():
            return
        self._auto_close(zone)

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
        elapsed = (time.monotonic() - self._open_monotonic) if self._open_monotonic else 0

        # Stop the watchdog for this open.
        if self._cancel is not None:
            self._cancel.set()

        self._safe_relay_off(zone)
        self._active_zone = None
        self._open_monotonic = None
        self._duration = None
        self._cancel = None
        self._watchdog = None

        logger.info(f"Valve zone {zone} CLOSED after {elapsed:.1f}s")
        threading.Thread(
            target=self._notify_subscribers,
            args=({"event": "valve_change", "zone": zone, "state": "closed"},),
            daemon=True
        ).start()
        return True, 200, "Closed", {"zone": zone, "elapsed_seconds": round(elapsed, 1)}

    def _auto_close(self, zone):
        """Called by the watchdog when the duration expires. Guarantees the
        relay ends up physically OFF, retrying on I2C errors and falling back
        to all_off()."""
        with self._lock:
            if self._active_zone != zone or self._cancel is None:
                # Already closed or superseded by another open.
                return
            self._safe_relay_off(zone)
            self._active_zone = None
            self._open_monotonic = None
            self._duration = None
            self._cancel = None
            self._watchdog = None
            logger.info(f"Valve zone {zone} AUTO-CLOSED (duration expired)")
        self._notify_subscribers({"event": "valve_change", "zone": zone, "state": "closed"})

    def _safe_relay_off(self, zone):
        """Turn a zone's relay OFF, retrying on failure; fall back to all_off().
        Must be tolerant of a flaky I2C bus so a valve is never left energized."""
        for attempt in range(_OFF_RETRIES):
            try:
                self.relay.set_relay(zone, False)
                return
            except Exception as e:
                logger.error(
                    f"Zone {zone} relay OFF attempt {attempt + 1}/{_OFF_RETRIES} failed: {e}"
                )
                time.sleep(_OFF_RETRY_DELAY)
        logger.critical(
            f"Zone {zone} relay OFF failed after {_OFF_RETRIES} retries — forcing ALL relays OFF"
        )
        try:
            self.relay.all_off()
        except Exception as e:
            logger.critical(f"all_off() also failed for zone {zone}: {e}")

    def _auto_close_now_for_test(self):
        """Test hook: not used in production."""
        with self._lock:
            if self._active_zone is not None:
                self._do_close()

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
                elapsed = time.monotonic() - self._open_monotonic
                remaining = max(0, self._duration - elapsed)
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
        if self._open_monotonic is None or self._duration is None:
            return 0
        elapsed = time.monotonic() - self._open_monotonic
        return max(0, self._duration - elapsed)

    def shutdown(self):
        """Clean shutdown: close any active valve."""
        with self._lock:
            if self._active_zone is not None:
                self._do_close()
        self.relay.cleanup()
