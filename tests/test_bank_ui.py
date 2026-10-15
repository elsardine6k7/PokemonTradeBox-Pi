"""Run the actual TradeBox/Bank callbacks with the existing fake GTK scheduler."""
import copy
import unittest

from startup_checks import DEFAULT_CONFIG
from test_session_control import Process
import test_tradebox_operations as operations


class BankCallbacksTests(unittest.TestCase):
    setUp = operations.TradeBoxOperationTests.setUp
    close_streams = operations.TradeBoxOperationTests.close_streams
    complete_reset = operations.TradeBoxOperationTests.complete_reset

    def configure(self):
        self.rpc = []
        self.app._bank_rpc = lambda action, payload, callback, **kwargs: self.rpc.append((action, payload, callback))
        self.app.show_bank = lambda *_: None
        self.app.show_bank_queue = lambda *_: None
        self.app._bank_confirm_prepared = lambda *_: None
        self.app._bank_available = True
        self.app._bank_config = copy.deepcopy(DEFAULT_CONFIG)
        keys = self.root / "keys"
        keys.write_text("test", encoding="utf-8")
        self.app._bank_config["prod_keys"] = str(keys)
        (self.root / "logs").mkdir()
        self.app.bank_queue = [{"id": "first", "summary": "First"}, {"id": "second", "summary": "Second"}]

    def prepared(self):
        self.app.bank_prepare_trade()
        action, payload, callback = self.rpc.pop(0)
        self.assertEqual(action, "begin")
        self.assertEqual(payload["ids"], ["first", "second"])
        self.assertTrue(self.app._bank_busy)
        callback({"offers": [{"bank": "first", "file": "one", "summary": "First"},
                             {"bank": "second", "file": "two", "summary": "Second"}], "cmd": ["bank-host"]}, "")
        self.assertFalse(self.app._bank_busy)
        return self.app._bank_run

    def active(self):
        run = self.prepared()
        run["state"], run["proc"] = "active", Process()
        self.app.proc = run["proc"]
        return run

    def test_preparing_then_cancelling_never_launches_or_clears_the_queue(self):
        self.configure()
        run = self.prepared()
        self.app.bank_cancel_prepared()
        self.assertEqual(self.rpc[-1][0], "end")
        self.rpc[-1][2]({"token": run["token"], "completed": 0, "total": 2}, "")
        self.assertIsNone(self.app._bank_run)
        self.assertEqual([item["id"] for item in self.app.bank_queue], ["first", "second"])
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])

    def test_bank_host_starts_only_after_reset_and_attaches_its_exact_pid(self):
        self.configure()
        run = self.prepared()
        self.app.bank_start_prepared()
        self.assertEqual(self.spawns, [])
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)
        self.assertIs(run["proc"], self.app.proc)
        self.assertEqual(self.rpc[-1][0], "attach")
        self.assertEqual(self.rpc[-1][1]["pid"], self.app.proc.pid)
        self.assertIn(f"bank-{run['token']}.log", self.app.proc_log.name)

    def test_cancel_after_start_cannot_race_the_pending_radio_callback(self):
        self.configure()
        self.prepared()
        self.app.bank_start_prepared()
        self.app.bank_cancel_prepared()
        self.assertEqual(self.rpc, [])
        self.assertIn("Wait", self.app.current_label)
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)

    def test_replacement_host_waits_for_final_bank_confirmation_before_reset(self):
        self.configure()
        run = self.active()
        old = run["proc"]
        self.app.launch(["replacement-host"], "Trade")
        self.assertEqual(len(old.signals), 1)
        old.returncode = 0
        self.assertTrue(self.app._poll_radio_operation())
        self.assertTrue(self.app.poll_process(old))
        self.assertEqual(self.rpc[-1][0], "end")
        self.assertEqual(len(self.rpc), 1)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.rpc[-1][2]({"token": run["token"], "completed": 1, "total": 2}, "")
        self.assertEqual([item["id"] for item in self.app.bank_queue], ["second"])
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(self.resets, ["reset"])
        self.assertFalse(self.app.poll_process(old))

    def test_completed_queue_automatically_stops_only_its_host(self):
        self.configure()
        run = self.active()
        unrelated = Process(pid=999)
        self.assertTrue(self.app._bank_poll_progress(run["token"]))
        self.rpc[-1][2]({"token": run["token"], "completed": 2, "total": 2}, "")
        self.assertEqual(len(run["proc"].signals), 1)
        self.assertEqual(unrelated.signals, [])
        self.assertEqual(self.app.bank_queue, [])

    def test_stale_progress_callback_cannot_discard_a_new_queue(self):
        self.configure()
        run = self.active()
        token = run["token"]
        self.app._bank_poll_progress(token)
        old_callback = self.rpc[-1][2]
        run["token"] = "b" * 32
        self.app.bank_queue = [{"id": "new", "summary": "New"}]
        old_callback({"token": token, "completed": 5, "total": 2}, "")
        self.assertEqual(self.app.bank_queue[0]["id"], "new")
        self.assertEqual(run["proc"].signals, [])

    def test_finish_failure_keeps_reservation_until_retry_succeeds(self):
        self.configure()
        run = self.active()
        self.app.stop_current_session()
        run["proc"].returncode = 0
        self.app._poll_radio_operation()
        self.rpc[-1][2](None, "Bank disk is not writable")
        self.assertTrue(self.app.session_control.busy)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.app.bank_retry_finish()
        self.rpc[-1][2]({"token": run["token"], "completed": 1, "total": 2}, "")
        self.complete_reset()
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.app.bank_queue[0]["id"], "second")

    def test_import_cannot_block_stop_of_an_existing_regular_host(self):
        self.configure()
        proc = self.app.proc = Process()
        self.app.bank_import("save.dat")
        self.assertEqual(self.rpc, [])
        self.assertFalse(self.app._bank_busy)
        self.app.stop_current_session()
        self.assertEqual(len(proc.signals), 1)

    def test_import_supplies_trainers_for_all_seven_native_bank_games(self):
        self.configure()
        self.app.bank_import("save.dat")
        payload = self.rpc[-1][1]
        self.assertEqual(set(payload["trainers"]), {"frlg", "lgpe", "swsh", "bdsp", "pla", "sv", "za"})
        self.assertEqual(payload["trainers"]["sv"], self.app._bank_config["trainers"]["za"])

    def test_startup_checks_cannot_rebind_backend_during_bank_preparation(self):
        self.configure()
        self.prepared()
        self.app.run_startup_checks()
        self.assertFalse(self.app._startup_busy)
        self.assertIn("Bank run", self.app.current_label)

    def test_regular_session_exit_is_never_a_bank_confirmation(self):
        self.configure()
        proc = self.app.proc = Process()
        proc.returncode = 0
        self.assertFalse(self.app.poll_process(proc))
        self.assertEqual(self.rpc, [])

    def test_regular_trade_registers_receiving_before_launch_and_preserves_bank_queue(self):
        self.configure()
        self.app.launch(["host", "--received", "old.pk8"], "Regular trade",
                        bank_game="swsh", offers=[{"file": "built.pk8"}])
        self.complete_reset()
        self.assertTrue(self.app.session_control.busy)
        self.assertEqual(self.spawns, [])
        action, payload, callback = self.rpc.pop(0)
        self.assertEqual(action, "watch")
        self.assertEqual(payload["game"], "swsh")
        callback({"cmd": ["host", "--received", "new.pk8"]}, "")
        run = self.app._bank_run
        self.assertTrue(run["regular"])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.spawns[0][0][-1], "new.pk8")
        self.app._bank_poll_progress(run["token"])
        received = {"id": "retail-mon", "summary": "Received Pikachu"}
        self.rpc[-1][2]({"token": run["token"], "completed": 1, "total": 1,
                        "received_count": 1, "received_entries": [received]}, "")
        self.assertEqual([entry["id"] for entry in self.app.bank_queue], ["first", "second"])
        self.assertEqual(self.app.bank_entries, [received])
        self.assertEqual(run["proc"].signals, [])
        self.assertIn("1 received Pokemon added", self.app.current_label)
        run["proc"].returncode = 0
        self.assertTrue(self.app.poll_process(run["proc"]))
        self.assertEqual(self.rpc[-1][0], "end")
        self.rpc[-1][2]({"token": run["token"], "completed": 1, "total": 1,
                        "received_count": 1, "received_entries": [received]}, "")
        self.assertEqual(self.app.bank_entries, [received])
        self.assertIsNone(self.app._bank_run)

    def test_regular_receiving_preparation_failure_releases_radio_without_launching(self):
        self.configure()
        self.app.launch(["host"], "Trade", bank_game="za", offers=[])
        self.complete_reset()
        self.rpc[-1][2](None, "Unfinished run needs reconciliation")
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.spawns, [])
        self.assertIn("reconciliation", self.app.current_label)

    def test_regular_trade_on_api_13_keeps_existing_host_behavior(self):
        self.configure()
        self.app._bank_available = False
        self.app.launch(["host"], "Trade", bank_game="swsh", offers=[])
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(self.rpc, [])
        self.assertIsNone(self.app._bank_run)

    def test_reset_failure_returns_prepared_queue_to_retry_or_cancel(self):
        self.configure()
        run = self.prepared()
        def failed_reset():
            raise OSError("Board disconnected")
        self.app.reset_esp32 = failed_reset
        self.app.bank_start_prepared()
        self.complete_reset()
        self.assertEqual(run["state"], "prepared")
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.spawns, [])
        self.assertIn("Board disconnected", self.app.current_label)
        self.app.bank_cancel_prepared()
        self.rpc[-1][2]({"token": run["token"], "completed": 0, "total": 2}, "")
        self.assertIsNone(self.app._bank_run)
        self.assertEqual(len(self.app.bank_queue), 2)

    def test_attach_submission_failure_stops_the_spawned_host(self):
        self.configure()
        run = self.prepared()
        def broken_rpc(*_args, **_kwargs):
            raise OSError("Cannot submit Bank request")
        self.app._bank_rpc = broken_rpc
        self.app.bank_start_prepared()
        self.complete_reset()
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(run["state"], "active")
        self.assertEqual(len(run["proc"].signals), 1)
        self.assertEqual(self.app.session_control.operation, "stop")
        self.assertIn("Cannot submit", run["error"])

    def test_bank_launcher_start_failure_keeps_queue_and_finishes_preparation(self):
        self.configure()
        run = self.prepared()
        self.spawn_error = OSError("Host executable missing")
        self.app.bank_start_prepared()
        self.complete_reset()
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.rpc[-1][0], "end")
        self.rpc[-1][2]({"token": run["token"], "completed": 0, "total": 2}, "")
        self.assertIsNone(self.app._bank_run)
        self.assertEqual(len(self.app.bank_queue), 2)
        self.assertIn("Host executable missing", self.app.current_label)


if __name__ == "__main__":
    unittest.main()
