"""Exercise the actual TradeBox callbacks without GTK, pokeldn, or serial hardware.

Only the application class is compiled from its AST, avoiding module startup's
configuration and backend imports. The callbacks run unchanged with a fake
GLib scheduler and subprocesses; no real process or device is touched.
"""

import ast
import io
import json
import os
import tempfile
import time
import types
import unittest
from pathlib import Path

from session_control import SessionControl
from startup_checks import Check, StartupReport, check_startup, key_problem
from test_session_control import Clock, Process


class Application:
    def __init__(self, **_kwargs):
        self.quit_called = False

    def quit(self):
        self.quit_called = True


class Scheduler:
    def __init__(self):
        self.timers = []
        self.idles = []

    def timeout_add(self, delay, callback, *args):
        self.timers.append((delay, callback, args))
        return len(self.timers)

    timeout_add_seconds = timeout_add

    def idle_add(self, callback, *args):
        self.idles.append((callback, args))

    def drain(self):
        while self.idles:
            callback, args = self.idles.pop(0)
            callback(*args)


class Worker:
    def __init__(self, *, target, daemon):
        self.target = target
        if not daemon:
            raise AssertionError("Radio worker must not hold the application open.")

    def start(self):
        self.target()  # Completion still waits for the scheduled GTK callback.


class Button:
    def __init__(self):
        self.enabled = True

    def set_sensitive(self, enabled):
        self.enabled = enabled


class TradeBoxOperationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.clock = Clock()
        self.scheduler = Scheduler()
        self.spawns = []
        self.resets = []
        self.spawn_error = None

        def spawn(cmd, **kwargs):
            if self.spawn_error:
                raise self.spawn_error
            proc = Process(pid=200 + len(self.spawns))
            proc.stdout = io.StringIO(json.dumps({"ok": True, "protocol_current": True}))
            self.spawns.append((cmd, kwargs, proc))
            return proc

        self.worker_module = types.SimpleNamespace(Thread=Worker)
        namespace = {
            "Gtk": types.SimpleNamespace(Application=Application),
            "GLib": self.scheduler,
            "SessionControl": SessionControl,
            "threading": self.worker_module,
            "subprocess": types.SimpleNamespace(Popen=spawn, PIPE=-1, STDOUT=-2),
            "Path": Path, "os": os, "json": json, "time": time,
            "APP_DIR": self.root, "LOG_DIR": self.root, "REPO": self.root,
            "PYTHON": self.root / "python", "RADIO": "auto",
            "CONFIG_PATH": self.root / "config.json", "APP_VERSION": "0.4.3",
            "Check": Check, "StartupReport": StartupReport, "check_startup": check_startup,
            "radio_problem": lambda _radio: "", "key_problem": key_problem,
        }
        self.namespace = namespace
        source = Path(__file__).resolve().parents[1] / "tradebox.py"
        parsed = ast.parse(source.read_text(encoding="utf-8"))
        application = next(node for node in parsed.body
                           if isinstance(node, ast.ClassDef) and node.name == "TradeBox")
        module = ast.Module(body=[ast.ImportFrom(module="__future__",
                             names=[ast.alias(name="annotations")], level=0), application],
                            type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), str(source), "exec"), namespace)
        self.app = namespace["TradeBox"]()
        self.app._backend_ready = True  # Existing operation tests begin after startup.
        self.app.session_control = SessionControl(clock=self.clock)
        self.app.reset_esp32 = lambda: self.resets.append("reset")
        self.app._serial_radio_device = lambda: self.root / "radio"
        self.app.stop_button = Button()
        self.app.esp32_buttons = [Button(), Button(), Button()]
        self.app.set_status = lambda text: setattr(self.app, "current_label", text)
        self.addCleanup(self.close_streams)

    def close_streams(self):
        if self.app.proc_log:
            self.app.proc_log.close()
        for _cmd, _kwargs, proc in self.spawns:
            proc.stdout.close()

    def complete_reset(self):
        self.assertFalse(self.app._poll_radio_operation())
        self.assertEqual(self.app.session_control.phase, "resetting")
        self.scheduler.drain()

    def test_stop_returns_immediately_and_resets_only_after_process_exit(self):
        proc = self.app.proc = Process()
        self.app.stop_current_session()
        self.assertEqual(self.app.current_label, "Stopping...")
        self.assertFalse(self.app.stop_button.enabled)
        self.assertTrue(self.app._poll_radio_operation())
        self.assertEqual(self.resets, [])
        proc.returncode = 0
        self.complete_reset()
        self.assertEqual(self.resets, ["reset"])
        self.assertFalse(self.app.session_control.busy)
        self.assertTrue(self.app.stop_button.enabled)
        self.assertEqual(self.app.current_label, "Stopped. ESP32 ready.")

    def test_launch_stop_and_second_helper_are_blocked_during_firmware_work(self):
        self.app.session_control.begin("firmware", None)
        self.app.session_control.mark_active()
        self.app.launch(["new-trade"], "Trade")
        self.app.stop_current_session()
        self.app._start_esp32_action("check")
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])
        self.assertEqual(self.app.session_control.operation, "firmware")

    def test_trade_builders_and_gift_writes_are_refused_while_radio_is_reserved(self):
        self.app.session_control.begin("firmware", None)
        self.app.session_control.mark_active()
        for method in (self.app.host_za, self.app.host_swsh_trade,
                       self.app.host_bdsp_trade, self.app.host_frlg_trade):
            method(None, None)
        self.app.save_and_host_gift(None, "Gift")
        self.app._host_frlg_custom(None, "Gift", "gift.pokegift")
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_firmware_waits_for_shutdown_and_holds_radio_until_helper_exits(self):
        old = self.app.proc = Process()
        self.app._start_esp32_action("check")
        self.assertTrue(self.app._poll_radio_operation())
        self.assertEqual(self.spawns, [])
        old.returncode = 0
        self.app._poll_radio_operation()
        self.assertEqual(self.spawns, [])  # GTK has not taken the reset completion yet.
        self.scheduler.drain()
        self.assertEqual(len(self.spawns), 1)
        helper = self.spawns[0][2]
        self.app.launch(["new-trade"], "Trade")
        self.assertEqual(len(self.spawns), 1)
        self.assertTrue(self.app.session_control.busy)
        helper.returncode = 0
        self.assertFalse(self.app._poll_esp32_action())
        self.assertFalse(self.app.session_control.busy)
        self.assertTrue(all(button.enabled for button in self.app.esp32_buttons))

    def test_failed_stop_cancels_firmware_request_even_if_process_exits_later(self):
        old = self.app.proc = Process()
        self.app._start_esp32_action("flash")
        self.clock.now = 15
        self.app._poll_radio_operation()
        self.clock.now = 20
        self.app._poll_radio_operation()
        self.assertEqual(self.app.session_control.phase, "failed")
        self.app.launch(["new-trade"], "Trade")
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        old.returncode = 0
        self.assertFalse(self.app._poll_radio_operation())
        self.scheduler.drain()
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("Retry", self.app.current_label)

    def test_reset_failure_cancels_launch_and_releases_radio(self):
        def reset():
            raise OSError("USB disconnected")
        self.app.reset_esp32 = reset
        self.app.launch(["new-trade"], "Trade")
        self.complete_reset()
        self.assertEqual(self.spawns, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("USB disconnected", self.app.current_label)

    def test_reset_failure_cancels_firmware_work(self):
        def reset():
            raise OSError("USB disconnected")
        self.app.reset_esp32 = reset
        self.app._start_esp32_action("flash")
        self.complete_reset()
        self.assertEqual(self.spawns, [])
        self.assertFalse(self.app.esp32_busy)
        self.assertFalse(self.app.session_control.busy)

    def test_reset_worker_start_failure_releases_radio(self):
        class BrokenWorker:
            def __init__(self, **_kwargs):
                pass

            def start(self):
                raise RuntimeError("cannot start thread")

        self.worker_module.Thread = BrokenWorker
        self.app.launch(["new-trade"], "Trade")
        self.assertFalse(self.app._poll_radio_operation())
        self.assertFalse(self.app.session_control.busy)
        self.assertIsNone(self.app._reset_thread)
        self.assertEqual(self.spawns, [])
        self.assertIn("cannot start thread", self.app.current_label)

    def test_new_trade_starts_only_after_old_process_and_reset_finish(self):
        old = self.app.proc = Process()
        self.app.launch(["new-trade"], "Trade")
        self.assertTrue(self.app._poll_radio_operation())
        self.assertEqual(self.spawns, [])
        old.returncode = 0
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(self.resets, ["reset"])
        self.assertFalse(self.app.session_control.busy)
        self.assertIs(self.app.proc, self.spawns[0][2])

    def test_launch_failure_closes_log_and_releases_radio(self):
        self.spawn_error = OSError("missing backend")
        self.app.launch(["new-trade"], "Trade", reset=False)
        self.assertFalse(self.app._poll_radio_operation())
        self.assertIsNone(self.app.proc_log)
        self.assertIsNone(self.app.proc)
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("missing backend", self.app.current_label)

    def test_helper_spawn_failure_releases_radio(self):
        self.spawn_error = OSError("missing helper")
        self.app._start_esp32_action("check")
        self.complete_reset()
        self.assertFalse(self.app.session_control.busy)
        self.assertFalse(self.app.esp32_busy)

    def test_old_process_pollers_leave_new_session_alone(self):
        old = Process()
        old.returncode = 0
        current = self.app.proc = Process(pid=789)
        self.app.current_label = "New trade running"
        self.assertFalse(self.app.poll_process(old))
        self.assertIs(self.app.proc, current)
        self.assertEqual(self.app.current_label, "New trade running")

    def test_process_exit_watcher_preserves_shutdown_status(self):
        old = self.app.proc = Process()
        self.app.stop_current_session()
        old.returncode = 0
        self.app.poll_process(old)
        self.assertEqual(self.app.current_label, "Stopping...")
        self.complete_reset()

    def test_window_close_waits_for_session_shutdown(self):
        old = self.app.proc = Process()
        self.assertTrue(self.app._close_requested())
        self.assertFalse(self.app.quit_called)
        old.returncode = 0
        self.complete_reset()
        self.assertTrue(self.app.quit_called)

    def test_window_close_is_blocked_during_firmware_operation(self):
        self.app.session_control.begin("firmware", None)
        self.app.session_control.mark_active()
        self.assertTrue(self.app._close_requested())
        self.assertFalse(self.app.quit_called)

    def test_missing_keys_blocks_host_before_stop_reset_or_spawn(self):
        old = self.app.proc = Process()
        self.app.launch(["host", "--keys", self.root / "missing.keys"], "Trade")
        self.assertEqual(old.signals, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.assertIn("Keys missing", self.app.current_label)
        # FR/LG hosts do not need console keys.
        self.app.launch(["frlg-host"], "FR/LG", reset=False)
        self.assertTrue(self.app.session_control.busy)

    def test_unplugged_radio_blocks_host_and_can_be_connected_without_restart(self):
        self.namespace["radio_problem"] = lambda _radio: "ESP32 not found"
        self.app.launch(["host"], "Trade")
        self.app._start_esp32_action("check")
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])
        self.assertFalse(self.app.session_control.busy)
        self.namespace["radio_problem"] = lambda _radio: ""
        self.app.launch(["host"], "Trade", reset=False)
        self.app._poll_radio_operation()
        self.assertEqual(len(self.spawns), 1)

    def test_unplugging_while_stopping_cancels_pending_host(self):
        old = self.app.proc = Process()
        self.app.launch(["host"], "Trade", reset=False)
        self.namespace["radio_problem"] = lambda _radio: "ESP32 not found"
        old.returncode = 0
        self.app._poll_radio_operation()
        self.assertEqual(self.spawns, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("ESP32 not found", self.app.current_label)

    def test_unplugging_while_stopping_cancels_pending_firmware_helper(self):
        old = self.app.proc = Process()
        self.app._start_esp32_action("check")
        self.namespace["radio_problem"] = lambda _radio: "ESP32 not found"
        old.returncode = 0
        self.complete_reset()
        self.assertEqual(self.spawns, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("ESP32 not found", self.app.current_label)

    def test_retry_reloads_fixed_config_and_opens_home_after_gtk_completion(self):
        shown = []
        self.app.show_startup = lambda: shown.append("checks")
        self.app.show_home = lambda: shown.append("home")
        self.app._load_backend = lambda _config: (None,) * 5
        self.namespace["check_startup"] = lambda path, _app: StartupReport(
            config=json.loads(path.read_text()), checks=[Check("Test", "ok", "Ready")])
        path = self.namespace["CONFIG_PATH"]
        path.write_text("{broken", encoding="utf-8")
        self.app.run_startup_checks()
        self.assertTrue(self.app._startup_busy)
        self.assertFalse(self.app._backend_ready)
        self.assertNotIn("home", shown)
        self.scheduler.drain()
        self.assertFalse(self.app._startup_busy)
        self.assertFalse(self.app._backend_ready)
        fixed = {"pokeldn_repo": str(self.root / "custom-backend"),
                 "prod_keys": str(self.root / "custom.keys"), "radio": "auto",
                 "frlg_version": "leafgreen", "trainers": {"frlg": {"ot": "RICK"}}}
        path.write_text(json.dumps(fixed), encoding="utf-8")
        self.app.run_startup_checks()
        self.scheduler.drain()
        self.assertTrue(self.app._backend_ready)
        self.assertEqual(shown[-1], "home")
        self.assertEqual(self.namespace["REPO"], self.root / "custom-backend")
        self.assertEqual(self.namespace["FRLG_VERSION"], "leafgreen")
        self.assertEqual(self.namespace["TRAINERS"]["frlg"]["ot"], "RICK")

    def test_startup_warning_allows_home_but_missing_serial_blocks_radio_work(self):
        shown = []
        self.app.show_startup = lambda: shown.append("checks")
        self.app.show_home = lambda: shown.append("home")
        report = StartupReport(config={"pokeldn_repo": str(self.root),
            "prod_keys": str(self.root / "keys"), "radio": "auto",
            "frlg_version": "firered", "trainers": {}},
            checks=[Check("Serial", "warning", "Missing")])
        self.app._startup_complete(report, (None,) * 5)
        self.assertTrue(self.app._backend_ready)
        self.assertEqual(shown, ["checks"])
        self.app.launch(["host"], "Trade")
        self.assertEqual(self.spawns, [])
        self.assertIn("pyserial", self.app.current_label)

    def test_checks_cannot_reload_config_during_live_session_or_firmware(self):
        self.app.show_startup = lambda: self.fail("Should not leave a live session")
        self.app.proc = Process()
        self.app.run_startup_checks()
        self.assertFalse(self.app._startup_busy)
        self.assertEqual(self.app.proc.signals, [])
        self.app.proc = None
        self.app.session_control.begin("firmware", None)
        self.app.session_control.mark_active()
        self.app.run_startup_checks()
        self.assertFalse(self.app._startup_busy)


if __name__ == "__main__":
    unittest.main()
