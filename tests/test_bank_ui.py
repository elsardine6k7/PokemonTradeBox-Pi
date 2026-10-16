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
        (self.root / "logs").mkdir(exist_ok=True)
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

    def test_completed_queue_keeps_host_alive_through_repeated_progress(self):
        self.configure()
        run = self.active()
        proc = run["proc"]
        unrelated = Process(pid=999)
        for _ in range(3):
            self.assertTrue(self.app._bank_poll_progress(run["token"]))
            self.rpc[-1][2]({"token": run["token"], "completed": 2, "total": 2}, "")
            self.assertTrue(self.app.poll_process(proc))
        self.assertIs(self.app.proc, proc)
        self.assertIsNone(proc.poll())
        self.assertEqual(proc.signals, [])
        self.assertEqual(unrelated.signals, [])
        self.assertEqual(self.app.bank_queue, [])
        self.assertIs(self.app._bank_run, run)
        self.assertEqual(run["state"], "active")
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual([action for action, *_ in self.rpc], ["progress"] * 3)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])

    def test_completed_queue_finishes_once_after_native_host_exit(self):
        self.configure()
        run = self.active()
        proc = run["proc"]
        self.app._bank_poll_progress(run["token"])
        result = {"token": run["token"], "completed": 2, "total": 2}
        self.rpc[-1][2](result, "")
        self.assertTrue(self.app.poll_process(proc))
        self.assertEqual([action for action, *_ in self.rpc], ["progress"])

        proc.returncode = 0
        self.assertTrue(self.app.poll_process(proc))
        self.assertEqual([action for action, *_ in self.rpc], ["progress", "end"])
        self.assertEqual(self.rpc[-1][1], {"token": run["token"], "confirm_stopped": True})
        self.assertTrue(self.app.poll_process(proc))
        self.assertEqual([action for action, *_ in self.rpc], ["progress", "end"])
        self.rpc[-1][2](result, "")
        self.assertIsNone(self.app._bank_run)
        self.assertFalse(self.app.poll_process(proc))
        self.assertIsNone(self.app.proc)
        self.assertEqual(proc.signals, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])

    def test_progress_failure_preserves_live_host_until_exit_and_retry(self):
        self.configure()
        run = self.active()
        proc = run["proc"]
        self.app._bank_poll_progress(run["token"])
        self.rpc[-1][2](None, "Cannot inspect received Pokemon")
        self.assertEqual(run["error"], "Cannot inspect received Pokemon")
        self.assertEqual(proc.signals, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.resets, [])

        self.app.bank_retry_finish()
        self.assertEqual(run["error"], "Cannot inspect received Pokemon")
        self.assertTrue(self.app._bank_poll_progress(run["token"]))
        self.assertEqual([action for action, *_ in self.rpc], ["progress"])
        proc.returncode = 0
        self.assertTrue(self.app.poll_process(proc))
        self.assertEqual([action for action, *_ in self.rpc], ["progress"])

        self.app.bank_retry_finish()
        self.assertEqual([action for action, *_ in self.rpc], ["progress", "end"])
        self.rpc[-1][2]({"token": run["token"], "completed": 1, "total": 2}, "")
        self.assertIsNone(self.app._bank_run)
        self.assertFalse(self.app.poll_process(proc))
        self.assertEqual([item["id"] for item in self.app.bank_queue], ["second"])
        self.assertEqual(proc.signals, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])

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

    def configure_navigation(self, title="BANK BROWSER"):
        self.configure()
        self.shown, self.messages = [], []

        def show(title):
            self.app._current_page_title = title
            if title == "BANK BROWSER":
                self.app._bank_browser_generation = getattr(self.app, "_bank_browser_generation", 0) + 1
            self.shown.append(title)

        self.app.show_bank = lambda *_: show("POKEMON BANK")
        self.app.show_bank_browser = lambda *_: show("BANK BROWSER")
        self.app.show_bank_queue = lambda *_: show("BANK QUEUE - Legends Z-A")
        self.app._current_page_title = title

        def message(title, text, back):
            show(title)
            actions = []
            self.messages.append((title, text, back, actions))
            return actions

        self.app._bank_message = message
        self.app._bank_button = lambda label, callback, **kwargs: (label, callback, kwargs)
        self.entry = {"id": "first", "summary": "Dragonite, level 100", "game": "swsh", "legal": True}
        self.app.bank_entries = [self.entry]
        self.app.bank_page, self.app._bank_search = 2, "Dragonite"

    def test_refresh_keeps_browser_search_and_page_and_reconciles_queue(self):
        self.configure_navigation()
        self.app.bank_refresh()
        self.assertEqual(self.shown, ["BANK BROWSER"])
        self.assertTrue(self.app._bank_busy)
        self.rpc[-1][2]({"entries": [self.entry], "pending": []}, "")
        self.assertEqual(self.shown, ["BANK BROWSER", "BANK BROWSER"])
        self.assertEqual((self.app._bank_search, self.app.bank_page), ("Dragonite", 2))
        self.assertEqual([entry["id"] for entry in self.app.bank_queue], ["first"])
        self.assertFalse(self.app._bank_busy)

    def test_refresh_callback_updates_records_without_leaving_new_page(self):
        for destination in ("POKEMON BANK", "BANK QUEUE - Legends Z-A", "BANK POKEMON"):
            with self.subTest(destination=destination):
                self.configure_navigation()
                self.app.bank_refresh()
                self.app._current_page_title = destination
                self.shown.clear()
                updated = dict(self.entry, summary="Refreshed Dragonite")
                self.rpc[-1][2]({"entries": [updated], "pending": []}, "")
                self.assertEqual(self.app.bank_entries, [updated])
                self.assertEqual(self.app._current_page_title, destination)
                self.assertEqual(self.shown, [destination] if destination != "BANK POKEMON" else [])
                self.assertFalse(self.app._bank_busy)

    def test_browser_request_error_returns_to_browser_unless_user_left(self):
        for destination in ("BANK BROWSER", "POKEMON BANK", "BANK QUEUE - Legends Z-A"):
            with self.subTest(destination=destination):
                self.configure_navigation()
                self.app.bank_refresh()
                self.app._current_page_title = destination
                self.shown.clear()
                self.rpc[-1][2](None, "Bank temporarily unavailable")
                self.assertEqual(self.shown, [destination])
                self.assertEqual(self.app._current_page_title, destination)
                self.assertFalse(self.app._bank_busy)
                self.assertIn("temporarily unavailable", self.app.current_label)

    def test_details_back_and_enqueue_return_to_same_browser_page(self):
        self.configure_navigation()
        self.app.bank_queue = []
        self.app.bank_details(self.entry)
        self.assertEqual(self.rpc[-1][0], "details")
        self.rpc[-1][2]({"entry": self.entry, "route": {"ok": True}}, "")
        title, _text, back, actions = self.messages[-1]
        self.assertEqual(title, "BANK POKEMON")
        back()
        self.assertEqual(self.app._current_page_title, "BANK BROWSER")
        self.assertEqual((self.app._bank_search, self.app.bank_page), ("Dragonite", 2))
        add_to_queue = next(callback for label, callback, _kwargs in actions if label == "ADD TO QUEUE")
        add_to_queue()
        self.assertEqual(self.app.bank_queue, [self.entry])
        self.assertEqual(self.app._current_page_title, "BANK BROWSER")
        self.assertEqual((self.app._bank_search, self.app.bank_page), ("Dragonite", 2))

    def test_details_response_does_not_reopen_record_after_leaving_browser(self):
        self.configure_navigation()
        self.app.bank_details(self.entry)
        self.app.show_bank()
        self.shown.clear()
        self.rpc[-1][2]({"entry": self.entry, "route": {"ok": True}}, "")
        self.assertEqual(self.app._current_page_title, "POKEMON BANK")
        self.assertEqual(self.messages, [])
        self.assertEqual(self.shown, ["POKEMON BANK"])
        self.assertFalse(self.app._bank_busy)

    def test_details_response_does_not_open_record_after_browser_navigation(self):
        for navigation in ("next", "search", "reenter"):
            with self.subTest(navigation=navigation):
                self.configure_navigation()
                self.app.bank_details(self.entry)
                if navigation == "next":
                    self.app._bank_turn_page(1)
                elif navigation == "search":
                    self.app._bank_search = "Pikachu"
                    self.app.bank_page = 0
                    self.app.show_bank_browser()
                else:
                    self.app.show_bank()
                    self.app.show_bank_browser()
                self.messages.clear()
                self.rpc[-1][2]({"entry": self.entry, "route": {"ok": True}}, "")
                self.assertEqual(self.app._current_page_title, "BANK BROWSER")
                self.assertEqual(self.messages, [])
                self.assertFalse(self.app._bank_busy)

    def test_details_completion_refreshes_queue_controls_if_user_opened_queue(self):
        for error in ("", "Bank temporarily unavailable"):
            with self.subTest(error=error):
                self.configure_navigation()
                self.app.bank_details(self.entry)
                self.app.show_bank_queue()
                self.shown.clear()
                self.rpc[-1][2]({"entry": self.entry, "route": {"ok": True}} if not error else None, error)
                self.assertEqual(self.app._current_page_title, "BANK QUEUE - Legends Z-A")
                self.assertEqual(self.shown, ["BANK QUEUE - Legends Z-A"])
                self.assertEqual(self.messages, [])
                self.assertFalse(self.app._bank_busy)

    def test_remove_failure_returns_to_browser_with_search_and_page_intact(self):
        self.configure_navigation()
        self.app.bank_queue = []
        self.app.bank_confirm_remove(self.entry)
        _title, _text, back, actions = self.messages[-1]
        back()
        self.assertEqual(self.app._current_page_title, "BANK BROWSER")
        self.app.bank_confirm_remove(self.entry)
        self.messages[-1][3][0][1]()
        self.assertEqual(self.rpc[-1][0], "remove")
        self.rpc[-1][2](None, "Bank is read-only")
        self.assertEqual(self.app._current_page_title, "BANK BROWSER")
        self.assertEqual((self.app._bank_search, self.app.bank_page), ("Dragonite", 2))
        self.assertEqual(self.app.bank_entries, [self.entry])

    def test_remove_response_updates_records_without_reopening_browser_after_leaving(self):
        self.configure_navigation()
        self.app.bank_queue = []
        self.app.bank_confirm_remove(self.entry)
        self.messages[-1][3][0][1]()
        self.assertEqual(self.rpc[-1][0], "remove")
        self.app._current_page_title = "BANK QUEUE - Legends Z-A"
        self.shown.clear()
        self.rpc[-1][2]({}, "")
        self.assertEqual(self.app.bank_entries, [])
        self.assertEqual(self.app._current_page_title, "BANK QUEUE - Legends Z-A")
        self.assertEqual(self.shown, ["BANK QUEUE - Legends Z-A"])
        self.assertEqual(len(self.rpc), 1)
        self.assertFalse(self.app._bank_busy)


if __name__ == "__main__":
    unittest.main()
