"""Gift preparation and receipt boundaries, without PKHeX, radio, or a real Bank."""
import base64
import copy
import json
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

from bank_backend import BankEngine, catalog_trade_command, gift_code, trade_command


def field(flag, kind="text", default="", **kwargs):
    return types.SimpleNamespace(flag=flag, key=flag, kind=kind, default=default,
                                 **kwargs)


NO_CODE = "000000000000000000000000000000000000000000000000000000000000000000648cf400000000"


def catalog():
    tools = {}
    for game in ("za", "sv", "bdsp"):
        output = (("--save-theirs", "{received}/bdsp-{stamp}", "--ldn-protocol", "1",
                   "--complete-trade", "--language", "{language}", "--name", "{ot}",
                   "--trainer", "{ot}:{tid}:{sid}") if game == "bdsp" else
                  ("--offer-out", "{received}/" + game + "-{stamp}." + ("pa9" if game == "za" else "pk9"),
                   "--trainer-name", "{ot}"))
        if game == "sv":
            output += ("--clock", "--no-session-ack", "--send-at", "measured-first-packet",
                       "--send-at", "measured-second-packet", "--offer-after-open", "2")
        code = field("--password" if game == "bdsp" else "--code", "code",
                     "00000000" if game == "za" else "", unset=("--game-data", NO_CODE) if game == "sv" else ())
        for gift in (False, True):
            fields = [field("--offer" if game == "bdsp" else "--trade-offer", "pokemon", events=gift),
                      code, field("--fresh-pid", "switch", True)]
            if gift:
                fields.append(field("--for-receiver", "switch", True))
            key = f"{game}-{'gift-host' if gift else 'host'}"
            tools[key] = types.SimpleNamespace(key=key, script=f"bin/{game}_host.py", fixed=output,
                                               fields=tuple(fields), steps=("Offer and confirm.", "Exit after saving."))
    return tools


class GiftService:
    def __init__(self):
        self.calls = []
        self.replies = {}
        self.checked = []

    def gift_events(self, game, trainer):
        self.calls.append(("catalog", game, copy.deepcopy(trainer)))
        return [{"key": "1521-151-0-10", "title": "Get Mew", "species": "Mew", "legal": True}]

    def gift_event(self, game, key, trainer, *, keep=True):
        self.calls.append(("build", game, key, copy.deepcopy(trainer), keep))
        info = {"key": key, "title": key + " gift", "species": "Mew", "species_id": 151,
                "level": 5, "legal": True, "your_ot": True, "handled": False,
                "shiny": False, "home_tracker": "", "refused": "",
                "data": base64.b64encode(f"fresh:{len(self.calls)}".encode()).decode()}
        return dict(info, **self.replies.get(key, {}))

    def check(self, game, path):
        self.checked.append((game, path))
        return {"legal": True}


@dataclass
class Entry:
    id: str
    path: str


class Bank:
    class TradeSession:
        def __init__(self, offers, *, folder):
            self.offers = offers
            self.completed = 0

        def advance(self, count):
            self.completed = max(self.completed, count)

    def __init__(self):
        self.deposited = []

    def deposit(self, game, path, info, *, folder):
        self.deposited.append((game, path, info))
        return Entry(str(len(self.deposited)), path)


class GiftBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.tools = catalog()
        self.service = GiftService()
        self.bank = Bank()
        self.engine = BankEngine(self.bank,
            types.SimpleNamespace(trades_done=lambda line: int(line.split()[2])
                                  if line.startswith("[done] trade ") else None),
            types.SimpleNamespace(SERVICE=self.service), self.root, self.root / "pokeldn",
            self.root / "python", catalog_tools=self.tools)
        self.addCleanup(self.close_log)
        trainer = {"ot": "RICK", "tid": 123, "sid": 456, "language": 2, "gender": 0}
        self.config = {"prod_keys": "/configured/prod.keys",
                       "trainers": {game: dict(trainer) for game in ("za", "sv", "bdsp")}}

    def close_log(self):
        if self.engine.active:
            self.engine.active["log"].close()

    def prepare(self, game="sv", **changes):
        payload = {"game": game, "config": self.config, "keys": ["1521-151-0-10"],
                   "for_receiver": True}
        payload.update(changes)
        return self.engine.dispatch("gift_prepare", payload)

    def values(self, cmd, flag):
        return [cmd[index + 1] for index, arg in enumerate(cmd) if arg == flag]

    def watch(self, game="sv"):
        result = self.prepare(game)
        return self.engine.dispatch("watch", {"token": "a" * 32, "game": game,
                                              "offers": result["offers"], "cmd": result["cmd"]})

    def test_catalog_uses_the_requested_trainer_and_exposes_console_steps(self):
        trainer = dict(self.config["trainers"]["bdsp"], ot="DAWN")
        result = self.engine.dispatch("gift_catalog", {"game": "bdsp", "trainer": trainer})
        self.assertEqual(result["events"][0]["species"], "Mew")
        self.assertEqual(result["steps"], ["Offer and confirm.", "Exit after saving."])
        self.assertEqual(self.service.calls, [("catalog", "bdsp", trainer)])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_prepared_queue_keeps_order_duplicates_and_fresh_independent_files(self):
        result = self.prepare(keys=["same", "other", "same"])
        offers, cmd = result["offers"], result["cmd"]
        self.assertEqual([offer["event"] for offer in offers], ["same", "other", "same"])
        self.assertEqual(self.values(cmd, "--gift-event"), ["same", "other", "same"])
        self.assertEqual(self.values(cmd, "--trade-offer"), [offer["file"] for offer in offers])
        self.assertEqual(len({Path(offer["file"]).read_bytes() for offer in offers}), 3)
        self.assertTrue(all(Path(offer["file"]).is_relative_to(self.root / "gifts") for offer in offers))
        self.assertTrue(all("data" not in offer and "bank" not in offer for offer in offers))
        self.assertTrue(all(call[3] == self.config["trainers"]["sv"] and call[4] is False
                            for call in self.service.calls))
        self.assertIn("--fresh-pid", cmd)
        self.assertIn("--for-receiver", cmd)

    def test_sv_keeps_measured_fixed_arguments_and_no_code_payload(self):
        cmd = self.prepare()["cmd"]
        self.assertEqual(cmd[:3], [str(self.root / "python"), "-u", str(self.root / "pokeldn/bin/sv_host.py")])
        self.assertIn("--clock", cmd)
        self.assertIn("--no-session-ack", cmd)
        self.assertEqual(self.values(cmd, "--send-at"), ["measured-first-packet", "measured-second-packet"])
        self.assertEqual(self.values(cmd, "--game-data"), [NO_CODE])
        self.assertNotIn("--code", cmd)
        self.assertEqual(self.values(cmd, "--keys"), ["/configured/prod.keys"])

    def test_sv_explicit_code_omits_the_no_code_payload(self):
        cmd = self.prepare(code="00123456")["cmd"]
        self.assertEqual(self.values(cmd, "--code"), ["00123456"])
        self.assertNotIn("--game-data", cmd)

    def test_za_default_code_and_bdsp_native_trainer_save_flags(self):
        self.assertEqual(self.values(self.prepare("za")["cmd"], "--code"), ["00000000"])
        cmd = self.prepare("bdsp", code="87654321")["cmd"]
        self.assertEqual(self.values(cmd, "--password"), ["87654321"])
        self.assertEqual(self.values(cmd, "--trainer"), ["RICK:123:456"])
        self.assertEqual(self.values(cmd, "--language"), ["2"])
        self.assertEqual(self.values(cmd, "--ldn-protocol"), ["1"])
        self.assertIn("--complete-trade", cmd)
        self.assertEqual(Path(self.values(cmd, "--save-theirs")[0]).name, "received")

    def test_own_ot_and_handled_gifts_never_request_receiver_rebuilding(self):
        for change in ({"your_ot": False}, {"handled": True}):
            with self.subTest(change=change):
                self.service.replies["event"] = change
                result = self.prepare(keys=["event"])
                self.assertFalse(result["for_receiver"])
                self.assertNotIn("--for-receiver", result["cmd"])
                self.assertEqual(result["offers"][0]["handled"], change.get("handled", False))
        self.assertNotIn("--for-receiver", self.prepare(for_receiver=False)["cmd"])

    def test_mixed_queue_keeps_receiver_option_for_eligible_gift(self):
        self.service.replies["fixed"] = {"your_ot": False}
        self.assertIn("--for-receiver", self.prepare(keys=["fixed", "eligible"])["cmd"])

    def test_refusal_or_illegal_later_gift_does_not_write_partial_queue(self):
        for reply, reason in (({"refused": "never reached this language"}, "never reached"),
                              ({"legal": False, "report": "Wrong encounter"}, "Wrong encounter")):
            with self.subTest(reply=reply):
                self.service.replies["bad"] = reply
                with self.assertRaisesRegex(ValueError, reason):
                    self.prepare(keys=["good", "bad"])
                self.assertFalse((self.root / "gifts").exists())

    def test_queue_and_code_validation_happen_before_building(self):
        invalid = [{"keys": []}, {"keys": ["a"] * 7}, {"keys": "event"}, {"keys": [""]},
                   {"keys": [None]}, {"code": "123"}, {"code": "１２３４５６７８"},
                   {"code": 12345678}, {"for_receiver": "yes"}]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.prepare(**changes)
        with self.assertRaisesRegex(ValueError, "requires"):
            self.prepare("za", code="")
        self.assertEqual(self.service.calls, [])

    def test_unsupported_games_and_missing_capabilities_give_clear_errors(self):
        for action in ("gift_catalog", "gift_prepare"):
            with self.assertRaisesRegex(ValueError, "support"):
                self.engine.dispatch(action, {"game": "frlg", "trainer": {}})
        self.engine.pokemon.SERVICE = types.SimpleNamespace(gift_events=lambda *_: [])
        with self.assertRaisesRegex(ValueError, "Update PokeLDN"):
            self.prepare()
        self.engine.pokemon.SERVICE = self.service
        self.engine.catalog_tools = {}
        with self.assertRaisesRegex(ValueError, "Update PokeLDN"):
            self.prepare()

    def test_active_run_blocks_building_a_new_queue(self):
        self.engine.active = {"log": types.SimpleNamespace(close=lambda: None)}
        with self.assertRaisesRegex(ValueError, "previous Bank run"):
            self.prepare()
        self.assertEqual(self.service.calls, [])

    def test_native_sv_bank_command_uses_catalog_without_changing_identity(self):
        received = self.root / "received-bank/out.pk9"
        cmd = trade_command(self.root / "pokeldn", self.root / "python", self.config, "sv",
                            [{"file": "/bank/HoOh.pk9", "bank": "source"}], received,
                            catalog_tools=self.tools)
        self.assertEqual(self.values(cmd, "--offer-out"), [str(received)])
        self.assertEqual(self.values(cmd, "--send-at"), ["measured-first-packet", "measured-second-packet"])
        self.assertEqual(self.values(cmd, "--game-data"), [NO_CODE])
        self.assertNotIn("--fresh-pid", cmd)
        self.assertNotIn("--gift-event", cmd)
        self.assertNotIn("--for-receiver", cmd)

    def test_sv_watch_deposits_only_confirmed_incoming_and_preserves_offer_files(self):
        watched = self.watch()
        path = Path(watched["received"])
        self.assertEqual(self.values(watched["cmd"], "--offer-out"), [str(path)])
        path.write_bytes(b"retail Pokemon")
        self.assertEqual(self.engine.dispatch("progress", {"token": watched["token"]})["received_count"], 0)
        log = self.root / "logs" / f"bank-{watched['token']}.log"
        log.write_text("[done] trade 1 complete\n")
        result = self.engine.dispatch("progress", {"token": watched["token"]})
        self.assertEqual(result["received_count"], 1)
        self.assertEqual(self.bank.deposited[0][0], "sv")
        self.assertEqual(self.service.checked, [("sv", str(path))])
        self.assertEqual(self.engine.active["receipt"]["state"], "running")
        self.assertTrue(Path(watched["offers"][0]["file"]).exists())

    def test_notices_are_bounded_deduplicated_saved_and_never_count_as_trades(self):
        watched = self.watch("bdsp")
        log = self.root / "logs" / f"bank-{watched['token']}.log"
        log.write_text("unrelated [pop-up] fake\n[pop-up] First reason\n[pop-up] First reason\n"
                       "[pop-up] Second reason\n[pop-up] Third reason\n[pop-up] " + "x" * 1000 + "\n")
        result = self.engine.dispatch("progress", {"token": watched["token"]})
        self.assertEqual(result["completed"], 0)
        self.assertEqual(result["notices"], ["Second reason", "Third reason", "x" * 600])
        receipt = json.loads((self.root / "bank-data/runs" / f"{watched['token']}.json").read_text())
        self.assertEqual(receipt["notices"], result["notices"])
        self.assertEqual(self.bank.deposited, [])


if __name__ == "__main__":
    unittest.main()
