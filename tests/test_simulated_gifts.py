"""Exercise event-gift callbacks with the real launcher and no GTK or radio."""
import copy
import unittest

from simulated_gifts import SimulatedGiftUI, event_facts, event_matches
from startup_checks import DEFAULT_CONFIG
from test_session_control import Process
import test_tradebox_operations as operations


class SimulatedGiftCallbacksTests(unittest.TestCase):
    close_streams = operations.TradeBoxOperationTests.close_streams
    complete_reset = operations.TradeBoxOperationTests.complete_reset

    def setUp(self):
        operations.TradeBoxOperationTests.setUp(self)
        self.rpc, self.shown = [], []
        self.app._bank_rpc = self.request
        self.app._bank_available = True
        self.app._bank_config = copy.deepcopy(DEFAULT_CONFIG)
        keys = self.root / "keys"
        keys.write_text("test", encoding="utf-8")
        self.app._bank_config["prod_keys"] = str(keys)
        (self.root / "logs").mkdir()
        self.app._configure_simulated_gifts(True)
        self.app.show_simulated_gifts = lambda game, **_kwargs: self.show("catalog", game)
        self.app.show_simulated_gift_queue = lambda game: self.show("queue", game)
        self.app.show_simulated_gift_review = lambda game: self.show("review", game)
        self.show("catalog", "za")
        self.shown.clear()
        self.event = {"key": "test-event", "species": "Pikachu", "title": "Event Pikachu", "legal": True}

    def request(self, action, payload, callback, **kwargs):
        self.rpc.append((action, payload, callback, kwargs))

    def show(self, page, game):
        title = {"catalog": "MYSTERY GIFTS", "queue": "GIFT QUEUE", "review": "READY TO SEND"}[page]
        self.app._gift_game = game
        self.app._current_page_title = f"{title} • {game}"
        self.shown.append((page, game))

    def prepare(self, game="za"):
        state = self.app._gift_state(game)
        state["queue"] = [dict(self.event), dict(self.event)]
        self.show("queue", game)
        self.app._gift_prepare(game)
        action, _payload, callback, _kwargs = self.rpc.pop()
        self.assertEqual(action, "gift_prepare")
        result = {"cmd": ["gift-host", "--keys", self.app._bank_config["prod_keys"]],
                  "offers": [{"file": "gift-1.pk9", "summary": "First Pikachu"},
                             {"file": "gift-2.pk9", "summary": "Second Pikachu"}]}
        callback(result, "")
        return result

    def test_catalog_is_serialized_and_uses_each_games_configured_trainer(self):
        for game in ("za", "sv", "bdsp"):
            with self.subTest(game=game):
                trainer = dict(self.app._bank_config["trainers"][game], ot=f"Trainer {game}")
                self.app._bank_config["trainers"][game] = trainer
                self.show("catalog", game)
                self.assertTrue(self.app._gift_load_catalog(game))
                self.assertTrue(self.app._bank_busy)
                self.assertFalse(self.app._bank_cancel_allowed)
                self.assertFalse(self.app._gift_load_catalog(game))
                self.assertEqual(len(self.rpc), 1)
                action, payload, callback, options = self.rpc.pop()
                self.assertEqual(action, "gift_catalog")
                self.assertEqual(payload, {"game": game, "trainer": trainer})
                self.assertGreaterEqual(options["timeout"], 60)
                self.app._gift_add(game, self.event)
                self.assertEqual(self.app._gift_state(game)["queue"], [])
                callback({"events": [self.event], "steps": ["Join the local room."]}, "")
                self.assertFalse(self.app._bank_busy)
                self.assertEqual(self.app._gift_state(game)["events"], [self.event])
                self.assertEqual(self.shown[-1], ("catalog", game))
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])

    def test_catalog_completion_caches_events_without_navigating_after_leaving(self):
        for destination, game in (("HOME", None), ("GIFT QUEUE • za", "za")):
            with self.subTest(destination=destination):
                self.show("catalog", "za")
                self.app._gift_load_catalog("za")
                callback = self.rpc.pop()[2]
                self.app._current_page_title, self.app._gift_game = destination, game
                self.shown.clear()
                callback({"events": [self.event], "steps": []}, "")
                self.assertEqual(self.app._current_page_title, destination)
                self.assertEqual(self.shown, [])
                self.assertEqual(self.app._gift_state("za")["events"], [self.event])
                self.assertFalse(self.app._bank_busy)

    def test_switching_catalogs_defers_visible_games_request_until_worker_finishes(self):
        for error in ("", "Z-A event database unavailable"):
            with self.subTest(first_request_error=error):
                self.app._configure_simulated_gifts(True)
                self.show("catalog", "za")
                self.assertTrue(self.app._gift_load_catalog("za"))
                first_done = self.rpc.pop()[2]
                self.show("catalog", "sv")
                self.assertFalse(self.app._gift_load_catalog("sv"))
                self.assertEqual(self.rpc, [])
                self.shown.clear()
                first_done(None if error else {"events": [self.event]}, error)
                self.assertEqual(self.shown, [])
                self.assertEqual(self.app._current_page_title, "MYSTERY GIFTS • sv")
                self.assertTrue(self.app._bank_busy)
                self.assertEqual(len(self.rpc), 1)
                action, payload, second_done, _kwargs = self.rpc.pop()
                self.assertEqual(action, "gift_catalog")
                self.assertEqual(payload["game"], "sv")
                sv_event = dict(self.event, key="sv-event")
                second_done({"events": [sv_event]}, "")
                self.assertFalse(self.app._bank_busy)
                self.assertEqual(self.app._gift_state("sv")["events"], [sv_event])
                self.assertEqual(self.app._gift_state("za")["error"], error)
                self.assertEqual(self.shown, [("catalog", "sv")])
                self.assertEqual(self.rpc, [])

    def test_catalog_error_can_be_retried_without_reopening_a_page_after_leaving(self):
        self.app._gift_load_catalog("za")
        callback = self.rpc.pop()[2]
        self.app._current_page_title = "HOME"
        self.app.current_label = "Home screen"
        callback(None, "Event database unavailable")
        self.assertEqual(self.app._gift_state("za")["error"], "Event database unavailable")
        self.assertEqual(self.app.current_label, "Home screen")
        self.assertEqual(self.shown, [])
        self.assertFalse(self.app._bank_busy)
        self.assertTrue(self.app._gift_load_catalog("za"))
        self.rpc.pop()[2]({"events": [self.event]}, "")
        self.assertEqual(self.app._gift_state("za")["error"], "")

    def test_catalog_error_on_visible_page_returns_to_retryable_catalog(self):
        self.app._gift_load_catalog("za")
        self.rpc.pop()[2](None, "No event files")
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.shown, [("catalog", "za")])
        self.assertIn("No event files", self.app.current_label)

    def test_catalog_submission_failure_releases_busy_state(self):
        def failed_request(*_args, **_kwargs):
            raise OSError("Worker closed")
        self.app._bank_rpc = failed_request
        self.app._gift_load_catalog("za")
        self.assertFalse(self.app._bank_busy)
        self.assertIn("Worker closed", self.app._gift_state("za")["error"])
        self.assertEqual(self.spawns, [])

    def test_duplicate_events_are_allowed_up_to_six_and_games_keep_separate_queues(self):
        state = self.app._gift_state("za")
        state["prepared"] = {"stale": True}
        for _ in range(7):
            self.app._gift_add("za", self.event)
        self.assertEqual(len(state["queue"]), 6)
        self.assertEqual([item["key"] for item in state["queue"]], [self.event["key"]] * 6)
        self.assertIsNot(state["queue"][0], state["queue"][1])
        self.assertIsNone(state["prepared"])
        self.assertEqual(self.app._gift_state("sv")["queue"], [])
        self.assertEqual(self.app._gift_state("bdsp")["queue"], [])
        self.assertEqual(self.rpc, [])

    def test_refused_and_illegal_events_do_not_enter_queue(self):
        for fields, message in (({"refused": "This event needs HOME."}, "needs HOME"),
                                ({"legal": False}, "legally")):
            with self.subTest(fields=fields):
                self.app._gift_add("za", dict(self.event, **fields))
                self.assertEqual(self.app._gift_state("za")["queue"], [])
                self.assertIn(message, self.app.current_label)
        self.assertEqual(self.rpc, [])

    def test_removing_one_duplicate_invalidates_prepared_gifts_and_keeps_order(self):
        state = self.app._gift_state("za")
        second = dict(self.event, key="second", species="Eevee")
        state["queue"] = [dict(self.event), second, dict(self.event)]
        state["prepared"] = {"old": True}
        self.app._gift_remove("za", 1)
        self.assertEqual([item["key"] for item in state["queue"]], [self.event["key"]] * 2)
        self.assertIsNone(state["prepared"])
        self.assertEqual(self.shown, [("queue", "za")])

    def test_active_host_blocks_catalog_edits_preparation_and_start_without_stopping_it(self):
        proc = self.app.proc = Process()
        state = self.app._gift_state("za")
        state["queue"] = [self.event]
        state["prepared"] = {"cmd": ["gift-host"], "offers": []}
        self.assertFalse(self.app._gift_load_catalog("za"))
        self.app._gift_add("za", self.event)
        self.app._gift_remove("za", 0)
        self.app._gift_prepare("za")
        self.app._gift_start("za")
        self.assertEqual(state["queue"], [self.event])
        self.assertEqual(self.rpc, [])
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])
        self.assertEqual(proc.signals, [])

    def test_firmware_reservation_and_unfinished_bank_run_block_event_work(self):
        self.app.session_control.begin("firmware", None)
        self.app.session_control.mark_active()
        self.assertFalse(self.app._gift_load_catalog("za"))
        self.app._gift_add("za", self.event)
        self.assertEqual(self.app._gift_state("za")["queue"], [])
        self.app.session_control.finish()
        self.app._bank_run = {"token": "pending-run"}
        self.assertFalse(self.app._gift_load_catalog("sv"))
        self.app._gift_add("sv", self.event)
        self.assertEqual(self.app._gift_state("sv")["queue"], [])
        self.assertEqual(self.rpc, [])

    def test_prepare_supplies_ordered_keys_trainer_keys_code_and_receiver_preference(self):
        for game, code, receiver in (("za", "01234567", True),
                                     ("sv", "", False), ("bdsp", "87654321", True)):
            with self.subTest(game=game):
                state = self.app._gift_state(game)
                state.update(queue=[self.event, dict(self.event, key="second"), self.event],
                             code=code, for_receiver=receiver)
                self.show("queue", game)
                self.app._gift_prepare(game)
                action, payload, callback, _kwargs = self.rpc.pop()
                self.assertEqual(action, "gift_prepare")
                self.assertEqual(payload["game"], game)
                self.assertEqual(payload["keys"], ["test-event", "second", "test-event"])
                self.assertEqual(payload["code"], code)
                self.assertIs(payload["for_receiver"], receiver)
                self.assertEqual(payload["config"]["trainers"][game],
                                 self.app._bank_config["trainers"][game])
                self.assertEqual(payload["config"]["prod_keys"], self.app._bank_config["prod_keys"])
                self.assertTrue(self.app._bank_busy)
                self.assertEqual(self.shown[-1], ("queue", game))
                result = {"cmd": ["gift-host"], "offers": [{"file": "gift.pk9"}]}
                callback(result, "")
                self.assertIs(state["prepared"], result)
                self.assertEqual(self.shown[-1], ("review", game))
                self.assertFalse(self.app._bank_busy)
                self.assertEqual(self.spawns, [])
                self.assertEqual(self.resets, [])

    def test_prepare_completion_does_not_take_user_back_after_leaving(self):
        state = self.app._gift_state("za")
        state["queue"] = [self.event]
        self.app._gift_prepare("za")
        callback = self.rpc.pop()[2]
        self.app._current_page_title = "HOME"
        self.shown.clear()
        result = {"cmd": ["gift-host"], "offers": []}
        callback(result, "")
        self.assertIs(state["prepared"], result)
        self.assertEqual(self.shown, [])
        self.assertEqual(self.app._current_page_title, "HOME")
        self.assertEqual(self.spawns, [])

    def test_prepare_failure_preserves_queue_and_leaves_no_host(self):
        state = self.app._gift_state("za")
        state["queue"] = [self.event]
        self.show("queue", "za")
        self.shown.clear()
        self.app._gift_prepare("za")
        self.assertEqual(self.shown, [("queue", "za")])
        self.assertTrue(self.app._bank_busy)
        self.shown.clear()
        self.rpc.pop()[2](None, "Cannot create a legal gift")
        self.assertEqual(state["queue"], [self.event])
        self.assertIsNone(state["prepared"])
        self.assertEqual(self.shown, [("queue", "za")])
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.resets, [])

    def test_prepare_discards_result_if_code_receiver_or_event_selection_changes(self):
        for changed in ("code", "for_receiver", "keys"):
            with self.subTest(changed=changed):
                state = self.app._gift_state("za")
                state.update(queue=[dict(self.event)], code="01234567", for_receiver=True,
                             prepared=None)
                self.show("queue", "za")
                self.app._gift_prepare("za")
                self.assertTrue(self.app._bank_busy)
                callback = self.rpc.pop()[2]
                if changed == "keys":
                    state["queue"] = [dict(self.event, key="replacement")]
                elif changed == "code":
                    state["code"] = "76543210"
                else:
                    state["for_receiver"] = False
                self.shown.clear()
                callback({"cmd": ["old-gift-host"], "offers": [{"file": "old-gift.pk9"}]}, "")
                self.assertFalse(self.app._bank_busy)
                self.assertIsNone(state["prepared"])
                self.assertEqual(self.shown, [("queue", "za")])
                self.assertIn("Prepare the gifts again", self.app.current_label)
                self.app._gift_start("za")
                self.assertEqual(self.spawns, [])
                self.assertEqual(self.resets, [])

    def test_stale_prepare_completion_after_leaving_does_not_navigate_or_offer_old_gifts(self):
        state = self.app._gift_state("za")
        state["queue"] = [self.event]
        self.app._gift_prepare("za")
        callback = self.rpc.pop()[2]
        state["code"] = "12345678"
        self.app._current_page_title = "HOME"
        self.app.current_label = "Home screen"
        self.shown.clear()
        callback({"cmd": ["old-gift-host"], "offers": []}, "")
        self.assertIsNone(state["prepared"])
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.shown, [])
        self.assertEqual(self.app.current_label, "Home screen")

    def test_empty_queue_or_missing_keys_cannot_prepare(self):
        self.app._gift_prepare("za")
        state = self.app._gift_state("za")
        state["queue"] = [self.event]
        (self.root / "keys").unlink()
        self.app._gift_prepare("za")
        self.assertEqual(self.rpc, [])
        self.assertFalse(self.app._bank_busy)
        self.assertIn("Keys missing", self.app.current_label)
        self.app._gift_start("za")
        self.assertEqual(self.spawns, [])

    def test_start_resets_then_registers_received_banking_before_launching_exact_offers(self):
        result = self.prepare("sv")
        original_bank_queue = self.app.bank_queue = [{"id": "stored-pokemon"}]
        self.app._gift_start("sv")
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.rpc, [])
        self.complete_reset()
        self.assertEqual(self.resets, ["reset"])
        self.assertEqual(self.spawns, [])
        action, payload, callback, _kwargs = self.rpc.pop()
        self.assertEqual(action, "watch")
        self.assertEqual(payload["game"], "sv")
        self.assertEqual(payload["offers"], [{"file": "gift-1.pk9"}, {"file": "gift-2.pk9"}])
        self.assertEqual(payload["cmd"], result["cmd"])
        self.assertTrue(self.app.session_control.busy)
        watched_cmd = result["cmd"] + ["--received", "received.pk9"]
        callback({"cmd": watched_cmd}, "")
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(self.spawns[0][0], watched_cmd)
        self.assertTrue(self.app._bank_run["regular"])
        self.assertEqual(self.app._bank_run["offers"], result["offers"])
        self.assertIs(self.app.bank_queue, original_bank_queue)
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.rpc[-1][0], "attach")
        self.assertEqual(self.rpc[-1][1]["pid"], self.app.proc.pid)

    def test_received_banking_registration_failure_cannot_start_gift_host(self):
        self.prepare()
        self.app._gift_start("za")
        self.complete_reset()
        self.assertEqual(self.rpc[-1][0], "watch")
        self.rpc.pop()[2](None, "Reconcile unfinished run first")
        self.assertEqual(self.spawns, [])
        self.assertIsNone(self.app._bank_run)
        self.assertFalse(self.app.session_control.busy)
        self.assertIn("Reconcile unfinished", self.app.current_label)

    def test_gift_notice_reaches_its_games_queue_and_preserves_host_through_save(self):
        result = self.prepare("sv")
        result["offers"][0]["event"] = dict(self.event)
        self.app._gift_start("sv")
        self.complete_reset()
        self.rpc.pop()[2]({"cmd": result["cmd"]}, "")
        run = self.app._bank_run
        proc = self.app.proc
        self.assertEqual(run["game"], "sv")
        self.assertEqual(self.rpc.pop()[0], "attach")
        self.show("queue", "sv")
        self.shown.clear()
        notice = "This event was skipped because it cannot be made for the receiving player."
        for _ in range(2):
            self.assertTrue(self.app._bank_poll_progress(run["token"]))
            action, payload, callback, _kwargs = self.rpc.pop()
            self.assertEqual(action, "progress")
            self.assertEqual(payload, {"token": run["token"]})
            callback({"token": run["token"], "completed": 2, "total": 2,
                      "notices": [notice]}, "")
            self.assertIs(self.app._bank_run, run)
            self.assertIs(self.app.proc, proc)
            self.assertTrue(self.app.poll_process(proc))
        self.assertEqual(self.app._gift_state("sv")["notices"], [notice])
        self.assertEqual(self.app._gift_state("za").get("notices", []), [])
        self.assertEqual(self.shown, [("queue", "sv")])
        self.assertIn("Gift delivery has a notice", self.app.current_label)
        self.assertEqual(proc.signals, [])
        self.assertFalse(self.app.session_control.busy)
        self.assertEqual(self.rpc, [])
        self.assertEqual(self.resets, ["reset"])
        self.assertEqual(len(self.spawns), 1)

    def test_gift_notice_does_not_navigate_from_another_games_queue(self):
        proc = self.app.proc = Process()
        self.app._bank_run = {"token": "gift-run", "state": "active", "proc": proc,
                              "game": "sv", "completed": 0, "queue": [], "regular": True,
                              "offers": [{"event": dict(self.event)}]}
        self.app._gift_state("sv")
        self.show("queue", "za")
        self.shown.clear()
        self.app._bank_apply_progress({"token": "gift-run", "completed": 0,
                                       "notices": ["Receiver save could not be identified."]})
        self.assertEqual(self.shown, [])
        self.assertEqual(self.app._current_page_title, "GIFT QUEUE • za")
        self.assertEqual(self.app._gift_state("sv")["notices"],
                         ["Receiver save could not be identified."])
        self.assertEqual(proc.signals, [])

    def test_review_uses_prepared_receiver_support_and_shows_each_fixed_trainer(self):
        messages = []
        self.app._bank_message = lambda title, text, _back: messages.append((title, text)) or []
        self.app._bank_button = lambda label, callback, **kwargs: (label, callback, kwargs)
        state = self.app._gift_state("sv")
        state["for_receiver"] = True
        state["prepared"] = {"for_receiver": False, "offers": [
            {"summary": "Event Pikachu", "your_ot": True, "ot": "EVENT"}]}
        SimulatedGiftUI.show_simulated_gift_review(self.app, "sv")
        self.assertIn("Trainer: EVENT", messages[-1][1])
        self.assertNotIn("Trainer: the receiving player", messages[-1][1])
        state["prepared"] = {"for_receiver": True, "offers": [
            {"summary": "Eligible Pikachu", "your_ot": True, "ot": "PLAYER"},
            {"summary": "Fixed event Eevee", "ot": "ASH"},
            {"summary": "Handled gift", "your_ot": True, "handled": True, "ot": "Rick"}]}
        SimulatedGiftUI.show_simulated_gift_review(self.app, "sv")
        text = messages[-1][1]
        self.assertEqual(text.count("Trainer: the receiving player"), 1)
        self.assertIn("Trainer: ASH", text)
        self.assertIn("Trainer: Rick", text)
        self.assertIn("needs a handler", text)

    def test_disabled_feature_does_not_request_catalog_or_prepare_events(self):
        self.app._configure_simulated_gifts(False)
        self.assertFalse(self.app._gift_load_catalog("za"))
        self.app._gift_state("za")["queue"] = [self.event]
        self.app._gift_prepare("za")
        self.assertEqual(self.rpc, [])
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.spawns, [])


class EventSearchTests(unittest.TestCase):
    def test_search_combines_event_metadata_and_displayed_home_warning(self):
        event = {"title": "Summer Pikachu", "species": "Pikachu", "card_id": 1234,
                 "moves": ["Thunderbolt"], "tera": "Flying", "home_tracker": "empty"}
        for query in ("SUMMER pikachu", "1234 Thunderbolt", "tera flying", "HOME tracker"):
            with self.subTest(query=query):
                self.assertTrue(event_matches(event, query))
        self.assertFalse(event_matches(event, "Pikachu winter"))

    def test_event_facts_show_form_shiny_level_item_and_tera(self):
        facts = event_facts({"species": "Pikachu", "form": "World Cap", "level": 25,
                             "shiny": "always", "held_item": "Light Ball", "tera": "Flying"})
        for detail in ("Pikachu", "World Cap", "level 25", "Shiny", "Light Ball", "Tera Flying"):
            self.assertIn(detail, facts)


if __name__ == "__main__":
    unittest.main()
