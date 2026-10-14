"""PID-only shutdown and an exclusive reservation for radio operations.

The UI polls this controller; it never waits for a process on the GTK thread.
No GTK, serial device, or pokeldn installation is needed to test it.
"""

import signal
import time


class SessionControl:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.operation = None
        self.phase = "idle"
        self.process = None
        self.deadline = None
        self.error = ""

    @property
    def busy(self):
        return self.operation is not None

    def begin(self, operation, process):
        """Reserve the radio and begin stopping only the supplied process."""
        if self.busy:
            return False
        if not operation:
            raise ValueError("A radio operation needs a name.")

        self.operation = operation
        self.process = process
        self.error = ""
        if process is None or process.poll() is not None:
            self.phase = "ready"
            return True

        self.phase = "stopping"
        self.deadline = self.clock() + 15
        try:
            process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass  # The next poll confirms that the process has exited.
        except Exception as exc:
            self._fail(f"Could not send SIGINT to PID {process.pid}: {exc}")
        return True

    def poll(self):
        """Advance shutdown without waiting; failed stops keep the radio reserved."""
        if self.phase not in ("stopping", "terminating", "failed"):
            return self.phase

        if self.process.poll() is not None:
            self.phase = "failed-exited" if self.phase == "failed" else "ready"
            return self.phase

        if self.phase == "failed" or self.clock() < self.deadline:
            return self.phase

        if self.phase == "stopping":
            self.phase = "terminating"
            self.deadline = self.clock() + 5
            try:
                self.process.terminate()  # SIGTERM, to this Popen's PID only.
            except ProcessLookupError:
                pass
            except Exception as exc:
                self._fail(f"Could not send SIGTERM to PID {self.process.pid}: {exc}")
        else:
            self._fail(
                f"PID {self.process.pid} is still running after SIGINT and SIGTERM. "
                "New sessions and ESP32 operations are blocked until it exits."
            )
        return self.phase

    def _fail(self, error):
        self.error = error
        self.phase = "failed"

    def mark_resetting(self):
        if self.phase != "ready":
            raise RuntimeError("The previous process must exit before resetting the radio.")
        self.phase = "resetting"

    def mark_active(self):
        if self.phase not in ("ready", "resetting"):
            raise RuntimeError("The previous process must exit before starting an operation.")
        self.phase = "active"

    def finish(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Cannot release the radio while the previous process is running.")
        self.operation = None
        self.phase = "idle"
        self.process = None
        self.deadline = None
        self.error = ""
