import signal
import unittest

from session_control import SessionControl


class Clock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now


class Process:
    def __init__(self, pid=123):
        self.pid = pid
        self.returncode = None
        self.signals = []
        self.terminate_count = 0
        self.signal_error = None
        self.terminate_error = None

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        if self.signal_error:
            raise self.signal_error
        self.signals.append(value)

    def terminate(self):
        if self.terminate_error:
            raise self.terminate_error
        self.terminate_count += 1

    def wait(self, **_kwargs):
        raise AssertionError("Shutdown must not wait on the UI thread.")

    def kill(self):
        raise AssertionError("Shutdown must preserve pokeldn's SIGINT/SIGTERM contract.")


class SessionControlTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.control = SessionControl(clock=self.clock)
        self.process = Process()

    def test_stop_signals_only_the_process_supplied(self):
        unrelated = Process(pid=456)
        self.assertTrue(self.control.begin("stop", self.process))
        self.assertEqual(self.process.signals, [signal.SIGINT])
        self.assertEqual(unrelated.signals, [])
        for _ in range(10):
            self.assertEqual(self.control.poll(), "stopping")
        self.assertEqual(self.process.signals, [signal.SIGINT])

    def test_full_fifteen_second_grace_then_five_second_termination_wait(self):
        self.control.begin("launch", self.process)
        self.clock.now = 14.999
        self.assertEqual(self.control.poll(), "stopping")
        self.assertEqual(self.process.terminate_count, 0)
        self.clock.now = 15
        self.assertEqual(self.control.poll(), "terminating")
        self.assertEqual(self.process.terminate_count, 1)
        self.clock.now = 19.999
        self.assertEqual(self.control.poll(), "terminating")
        self.clock.now = 20
        self.assertEqual(self.control.poll(), "failed")
        self.assertTrue(self.control.busy)
        self.assertEqual(self.process.terminate_count, 1)

    def test_clean_exit_needs_no_sigterm(self):
        self.control.begin("launch", self.process)
        self.process.returncode = 0
        self.assertEqual(self.control.poll(), "ready")
        self.assertEqual(self.process.terminate_count, 0)
        self.control.mark_resetting()
        self.control.mark_active()
        self.control.finish()
        self.assertFalse(self.control.busy)

    def test_exit_after_sigterm_can_continue(self):
        self.control.begin("firmware", self.process)
        self.clock.now = 15
        self.control.poll()
        self.process.returncode = -15
        self.assertEqual(self.control.poll(), "ready")

    def test_already_exited_process_is_not_signalled(self):
        self.process.returncode = 1
        self.control.begin("stop", self.process)
        self.assertEqual(self.control.poll(), "ready")
        self.assertEqual(self.process.signals, [])

    def test_firmware_reservation_blocks_competing_actions(self):
        self.control.begin("firmware", None)
        self.control.mark_resetting()
        self.assertFalse(self.control.begin("launch", self.process))
        self.control.mark_active()
        self.assertFalse(self.control.begin("stop", self.process))
        self.assertEqual(self.process.signals, [])
        self.control.finish()
        self.assertTrue(self.control.begin("launch", self.process))

    def test_sigint_failure_retains_the_reservation_until_exit(self):
        self.process.signal_error = PermissionError("refused")
        self.control.begin("firmware", self.process)
        self.assertEqual(self.control.poll(), "failed")
        self.assertIn("SIGINT", self.control.error)
        self.assertFalse(self.control.begin("launch", None))
        self.process.returncode = 0
        self.assertEqual(self.control.poll(), "failed-exited")
        self.control.finish()
        self.assertFalse(self.control.busy)

    def test_sigterm_failure_keeps_reset_and_new_operations_blocked(self):
        self.control.begin("launch", self.process)
        self.process.terminate_error = PermissionError("refused")
        self.clock.now = 15
        self.assertEqual(self.control.poll(), "failed")
        self.assertIn("SIGTERM", self.control.error)
        with self.assertRaises(RuntimeError):
            self.control.mark_resetting()
        with self.assertRaises(RuntimeError):
            self.control.mark_active()
        with self.assertRaises(RuntimeError):
            self.control.finish()

    def test_process_lookup_race_is_confirmed_by_polling(self):
        self.process.signal_error = ProcessLookupError()
        self.control.begin("stop", self.process)
        self.assertEqual(self.control.poll(), "stopping")
        self.process.returncode = 0
        self.assertEqual(self.control.poll(), "ready")

    def test_failed_stop_is_distinct_from_a_successful_late_exit(self):
        self.control.begin("launch", self.process)
        self.clock.now = 15
        self.control.poll()
        self.clock.now = 20
        self.control.poll()
        self.clock.now = 30
        self.assertEqual(self.control.poll(), "failed")
        self.process.returncode = 0
        self.assertEqual(self.control.poll(), "failed-exited")


if __name__ == "__main__":
    unittest.main()
