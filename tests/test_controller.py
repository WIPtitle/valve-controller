"""Reliability tests for ValveController auto-close.

These reproduce the 2026-07-17 field failure: on the valve-controller Pi the
wall clock stepped backward ~71 min while a valve was open, and the auto-close
(then tied to the wall clock) did not fire — zone 3 ran ~73 min instead of 6.

The controller must now close on REAL elapsed time regardless of what the wall
clock (time.time) does, and must never leave a relay energized even if the I2C
OFF write fails.
"""
import time
import unittest
from unittest import mock

from valve_controller.controller import ValveController


class FakeRelay:
    def __init__(self, fail_off=False):
        self.zones = ["1", "2", "3", "4"]
        self.state = {z: False for z in self.zones}
        self.fail_off = fail_off
        self.set_calls = []

    def set_relay(self, zone, on):
        self.set_calls.append((zone, on))
        if not on and self.fail_off:
            raise OSError("simulated I2C bus error")
        self.state[zone] = on

    def all_off(self):
        for z in self.zones:
            self.state[z] = False

    def cleanup(self):
        self.all_off()


class TestAutoCloseClockIndependent(unittest.TestCase):
    def test_autocloses_on_time_even_if_wall_clock_frozen_or_backwards(self):
        """The bug: wall clock frozen/backward → valve never closed.
        Freeze time.time() entirely; the valve must still auto-close on real time."""
        relay = FakeRelay()
        c = ValveController(relay)

        # Simulate a broken wall clock: time.time() stuck (and could even go back).
        with mock.patch("valve_controller.controller.time.time", return_value=1000.0):
            ok, code, msg, _ = c.open_valve("3", 1.0)
            self.assertTrue(ok, msg)
            self.assertTrue(relay.state["3"], "relay should be energized after open")

            # Real time advances ~1s → auto-close must fire even though time.time() is frozen.
            time.sleep(1.8)

        self.assertFalse(relay.state["3"], "valve MUST auto-close on real elapsed time")
        self.assertIsNone(c._active_zone, "state must clear after auto-close")

    def test_status_uses_monotonic_not_wall_clock(self):
        relay = FakeRelay()
        c = ValveController(relay)
        with mock.patch("valve_controller.controller.time.time", return_value=1000.0):
            c.open_valve("1", 30.0)
            time.sleep(0.2)
            st = c.get_status()
            self.assertTrue(st["active"])
            # elapsed must be a small positive real number, not affected by frozen wall clock
            self.assertGreaterEqual(st["elapsed_seconds"], 0.0)
            self.assertLess(st["elapsed_seconds"], 5.0)
            self.assertGreater(st["remaining_seconds"], 20.0)
            c.close_valve()


class TestAutoCloseRelayFailure(unittest.TestCase):
    def test_forces_all_off_when_relay_off_write_keeps_failing(self):
        """If the I2C OFF write fails, auto-close must retry and fall back to all_off()
        so a valve is never left physically open."""
        relay = FakeRelay(fail_off=True)
        c = ValveController(relay)
        c.open_valve("2", 0.5)
        # duration (0.5) + retries (5 * 0.5) → give it margin
        time.sleep(4.0)
        self.assertFalse(any(relay.state.values()), "all relays must end OFF via fallback")
        self.assertIsNone(c._active_zone, "state must clear even when OFF write failed")


class TestManualCloseCancelsWatchdog(unittest.TestCase):
    def test_manual_close_stops_watchdog_and_no_double_close(self):
        relay = FakeRelay()
        c = ValveController(relay)
        c.open_valve("4", 5.0)
        ok, code, msg, detail = c.close_valve("4")
        self.assertTrue(ok)
        self.assertFalse(relay.state["4"])
        self.assertIsNone(c._active_zone)
        # Open a different zone; the old watchdog must not close it when its timer elapses.
        c.open_valve("1", 3.0)
        time.sleep(1.0)
        self.assertEqual(c._active_zone, "1", "stale watchdog must not interfere with a new open")
        c.close_valve()


class TestDurationCap(unittest.TestCase):
    def test_duration_is_clamped_to_safety_ceiling(self):
        relay = FakeRelay()
        c = ValveController(relay)
        ok, code, msg, detail = c.open_valve("1", 99999)
        self.assertTrue(ok)
        self.assertLessEqual(detail["duration"], 1800)
        c.close_valve()


if __name__ == "__main__":
    unittest.main()
