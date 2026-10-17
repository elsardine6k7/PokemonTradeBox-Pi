"""Scarlet/Violet Link Trade routing, safe preparation and receiving boundaries."""
import copy
import json
import types
import unittest
from pathlib import Path

from startup_checks import DEFAULT_CONFIG
import test_simulated_gift_backend as gifts
import test_tradebox_operations as operations


class SVTradeBackendTests(unittest.TestCase):
    setUp = gifts.GiftBackendTests.setUp
    close_log = gifts.GiftBackendTests.close_log
    values = gifts.GiftBackendTests.values

    def offers(self, count=2):
        result = []
        for index in range(count):
            path = self.root / f"built-{index}.pk9"
            path.write_bytes(f"built Pokemon {index}".encode())
            result.append({"file": str(path), "legal": True, "species": "Pikachu",
                           "summary": f"Pikachu {index}"})
        return result

    def prepare(self, offers=None, **changes):
        payload = {"game": "sv", "config": self.config,
                   "offers": self.offers() if offers is None else offers}
        payload.update(changes)
        return self.engine.dispatch("trade_prepare", payload)

    def test_native_command_keeps_offer_order_trainer_and_measured_no_code_setup(self):
        offers = self.offers()
        original = {Path(item["file"]): Path(item["file"]).read_bytes() for item in offers}
        result = self.prepare(offers)
        cmd = result["cmd"]
        self.assertEqual(result["offers"], offers)
        self.assertEqual(cmd[:3], [str(self.root / "python"), "-u",
                                  str(self.root / "pokeldn/bin/sv_host.py")])
        self.assertEqual(self.values(cmd, "--trade-offer"), [item["file"] for item in offers])
        self.assertEqual(self.values(cmd, "--trainer-name"), ["RICK"])
        self.assertEqual(self.values(cmd, "--keys"), [self.config["prod_keys"]])
        self.assertEqual(self.values(cmd, "--game-data"), [gifts.NO_CODE])
        self.assertEqual(self.values(cmd, "--send-at"),
                         ["measured-first-packet", "measured-second-packet"])
        self.assertIn("--clock", cmd)
        self.assertIn("--no-session-ack", cmd)
        for flag in ("--code", "--gift-event", "--for-receiver", "--fresh-pid"):
            self.assertNotIn(flag, cmd)
        self.assertEqual(result["steps"], list(self.tools["sv-host"].steps))
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertEqual(self.bank.deposited, [])
        self.assertEqual(self.service.calls, [])
        self.assertIsNone(self.engine.active)
        self.assertFalse((self.root / "bank-data").exists())

    def test_invalid_offers_never_create_run_or_mutate_bank(self):
        valid = self.offers(1)[0]
        invalid = [[], [valid] * 7, "not a queue", [None],
                   [dict(valid, legal=False)], [dict(valid, legal="yes")],
                   [{key: value for key, value in valid.items() if key != "legal"}],
                   [dict(valid, file=str(self.root / "missing.pk9"))],
                   [dict(valid, file=str(self.root))],
                   [dict(valid, bank="bank-record")], [dict(valid, event="gift-event")]]
        for offers in invalid:
            with self.subTest(offers=offers), self.assertRaises(ValueError):
                self.prepare(offers)
        with self.assertRaises(ValueError):
            self.prepare([valid], game="za")
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.bank.deposited, [])
        self.assertEqual(self.service.calls, [])
        self.assertFalse((self.root / "bank-data").exists())

    def test_active_or_unfinished_run_blocks_new_trade_preparation(self):
        offers = self.offers(1)
        self.engine.active = {"log": types.SimpleNamespace(close=lambda: None)}
        with self.assertRaisesRegex(ValueError, "previous Bank run"):
            self.prepare(offers)
        self.engine.active = None
        runs = self.root / "bank-data/runs"
        runs.mkdir(parents=True)
        (runs / ("b" * 32 + ".json")).write_text(json.dumps({
            "token": "b" * 32, "game": "sv", "state": "running", "pid": None,
        }))
        with self.assertRaisesRegex(ValueError, "previous Bank run"):
            self.prepare(offers)
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.bank.deposited, [])

    def test_missing_native_catalog_fails_without_creating_receipt(self):
        self.engine.catalog_tools = {}
        with self.assertRaisesRegex(ValueError, "Update PokeLDN"):
            self.prepare()
        self.assertFalse((self.root / "bank-data").exists())

    def test_regular_watch_banks_only_confirmed_receives_and_preserves_built_files(self):
        result = self.prepare()
        originals = {item["file"]: Path(item["file"]).read_bytes() for item in result["offers"]}
        watched = self.engine.dispatch("watch", {"token": "c" * 32, "game": "sv",
            "offers": result["offers"], "cmd": result["cmd"]})
        received = Path(watched["received"])
        received.write_bytes(b"first retail Pokemon")
        received.with_name(received.stem + "-2.pk9").write_bytes(b"second retail Pokemon")
        self.assertEqual(self.values(watched["cmd"], "--offer-out"), [str(received)])
        self.assertEqual(self.engine.dispatch("progress", {"token": watched["token"]})["received_count"], 0)
        log = self.root / "logs" / f"bank-{watched['token']}.log"
        log.write_text("[done] trade 1 complete\n[done] trade 2 complete\n")
        progress = self.engine.dispatch("progress", {"token": watched["token"]})
        self.assertEqual(progress["completed"], 2)
        self.assertEqual(progress["received_count"], 2)
        self.assertEqual([game for game, *_ in self.bank.deposited], ["sv", "sv"])
        self.assertEqual({path: Path(path).read_bytes() for path in originals}, originals)
        self.assertEqual(self.engine.active["receipt"]["state"], "running")


class SVTradeCallbacksTests(unittest.TestCase):
    close_streams = operations.TradeBoxOperationTests.close_streams
    complete_reset = operations.TradeBoxOperationTests.complete_reset

    def setUp(self):
        operations.TradeBoxOperationTests.setUp(self)
        self.rpc, self.builds, self.shown = [], [], []
        self.app._bank_rpc = lambda action, payload, callback, **kwargs: self.rpc.append(
            (action, payload, callback, kwargs))
        self.app._bank_available = True
        self.app._bank_config = copy.deepcopy(DEFAULT_CONFIG)
        keys = self.root / "keys"
        keys.write_text("test")
        self.app._bank_config["prod_keys"] = str(keys)
        self.namespace["KEYS"] = keys
        self.namespace["text_of"] = lambda view: (view or "").strip()
        self.app._current_page_title = "SCARLET / VIOLET • LINK TRADE • TEAM BUILDER"
        self.app.show_bank = lambda *_: self.shown.append("Bank")
        self.app.show_bank_queue = lambda *_: self.shown.append("Queue")
        self.app.bank_queue = [{"id": "existing", "summary": "Bank Pokemon"}]
        (self.root / "logs").mkdir()
        self.offers = [{"file": str(self.root / "built.pk9"), "legal": True}]

        def build(game, text):
            self.builds.append((game, text))
            return self.offers

        self.app.showdown_files = build

    def test_menu_exposes_link_trade_and_routes_to_shared_sv_builder(self):
        rows, editors = [], []
        self.app.page = lambda *_: types.SimpleNamespace(append=rows.append)
        self.app.button = lambda label, callback: (label, callback)
        self.app.win = types.SimpleNamespace(set_child=lambda _: None)
        self.app.showdown_editor = lambda *args: editors.append(args)
        self.app.show_sv()
        self.assertEqual([label for label, _ in rows],
                         ["LINK TRADE", "MYSTERY GIFT - SIMULATED", "RECEIVED POKÉMON"])
        rows[0][1]()
        self.assertEqual(editors, [("SCARLET / VIOLET • LINK TRADE", "sv",
                                   self.app.host_sv_trade, self.app.show_sv)])

    def test_prepare_registers_receiving_before_spawning_and_keeps_bank_queue(self):
        self.app.host_sv_trade(None, "Pikachu\nLevel: 50")
        self.assertEqual(self.builds, [("sv", "Pikachu\nLevel: 50")])
        action, payload, ready, _ = self.rpc.pop(0)
        self.assertEqual(action, "trade_prepare")
        self.assertEqual(payload, {"game": "sv", "config": self.app._bank_config,
                                   "offers": self.offers})
        self.assertTrue(self.app._bank_busy)
        self.assertEqual(self.spawns, [])
        ready({"cmd": ["sv-host", "--offer-out", "placeholder.pk9"],
               "offers": self.offers, "steps": []}, "")
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.spawns, [])
        self.complete_reset()
        self.assertEqual(self.spawns, [])
        action, payload, watch_ready, _ = self.rpc.pop(0)
        self.assertEqual(action, "watch")
        self.assertEqual(payload["game"], "sv")
        self.assertEqual(payload["offers"], [{"file": self.offers[0]["file"]}])
        watch_ready({"cmd": ["sv-host", "--offer-out", "unique-received.pk9"]}, "")
        self.assertEqual(len(self.spawns), 1)
        self.assertEqual(self.spawns[0][0][-1], "unique-received.pk9")
        self.assertTrue(self.app._bank_run["regular"])
        self.assertEqual(self.app._bank_run["game"], "sv")
        self.assertEqual(self.rpc[-1][0], "attach")
        self.assertEqual(self.app.bank_queue, [{"id": "existing", "summary": "Bank Pokemon"}])

    def test_empty_or_excessive_team_never_requests_worker_or_resets(self):
        for text, offers in (("", self.offers), ("Pikachu", []),
                             ("Pikachu", self.offers * 7)):
            with self.subTest(text=text, count=len(offers)):
                self.offers = offers
                self.app.host_sv_trade(None, text)
                self.assertEqual(self.rpc, [])
                self.assertEqual(self.spawns, [])
                self.assertEqual(self.resets, [])

    def test_busy_or_failed_prerequisites_block_building_and_worker_requests(self):
        for reason in ("bank", "radio", "startup"):
            with self.subTest(reason=reason):
                self.app._bank_busy = reason == "bank"
                self.app._backend_ready = reason != "startup"
                self.app._bank_run = {"state": "active"} if reason == "radio" else None
                self.app.host_sv_trade(None, "Pikachu")
                self.assertEqual(self.builds, [])
                self.assertEqual(self.rpc, [])
                self.assertEqual(self.spawns, [])
        self.app._bank_busy, self.app._bank_run = False, None

    def test_builder_failure_never_prepares_or_starts_a_host(self):
        def fail(*_):
            raise ValueError("Unavailable encounter")
        self.app.showdown_files = fail
        self.app.host_sv_trade(None, "Pikachu")
        self.assertIn("Unavailable encounter", self.app.current_label)
        self.assertEqual(self.rpc, [])
        self.assertEqual(self.resets, [])

    def test_worker_failure_preserves_editor_and_never_starts_host(self):
        self.app.host_sv_trade(None, "Pikachu")
        self.rpc.pop(0)[2](None, "No native S/V trade host")
        self.assertFalse(self.app._bank_busy)
        self.assertIn("No native S/V trade host", self.app.current_label)
        self.assertEqual(self.shown, [])
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])

    def test_leaving_editor_while_preparing_never_launches_from_stale_result(self):
        self.app.host_sv_trade(None, "Pikachu")
        ready = self.rpc.pop(0)[2]
        self.app._current_page_title = "SCARLET / VIOLET"
        ready({"cmd": ["sv-host", "--offer-out", "placeholder.pk9"],
               "offers": self.offers, "steps": []}, "")
        self.assertFalse(self.app._bank_busy)
        self.assertEqual(self.shown, [])
        self.assertEqual(self.resets, [])
        self.assertEqual(self.spawns, [])
        self.assertEqual(self.rpc, [])


if __name__ == "__main__":
    unittest.main()
