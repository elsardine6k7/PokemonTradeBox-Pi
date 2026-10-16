"""Bank boundary tests against the documented API contract, with no radio/PKHeX."""
import copy
import json
import os
import re
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from bank_backend import BankEngine, trade_command
from startup_checks import DEFAULT_CONFIG


@dataclass
class Entry:
    id: str
    path: str
    game: str = "swsh"
    species_id: int = 25
    shiny: bool = False
    summary: str = "Pikachu, level 5"
    legal: bool = True
    tracker: int = 0
    created: float = 0
    origin: str = ""
    home_tracker: str = ""


@dataclass
class ImportedPokemon:
    where: str
    species: str
    species_id: int
    shiny: bool
    state: str
    game: str
    detail: str


class FakeBank:
    """A strict fake: only documented methods are exposed to BankEngine."""
    def __init__(self, root):
        self.root = Path(root)
        self.held, self.removed, self.snapshots = {}, [], []
        self.refuse = None
        self.remove_error = None
        self.deposited = []
        self.deposit_error = None

    def deposit(self, game, source, info, *, folder):
        if self.deposit_error:
            raise OSError(self.deposit_error)
        content = Path(source).read_bytes()
        if any(Path(entry.path).read_bytes() == content for entry in self.held.values()):
            return None
        entry_id = f"incoming-{len(self.deposited) + 1}"
        path = self.root / f"banked-{entry_id}"
        path.write_bytes(content)
        entry = Entry(entry_id, str(path), game=game, legal=info["legal"])
        self.held[entry_id] = entry
        self.deposited.append((game, str(source), dict(info)))
        return entry

    def add(self, entry_id):
        path = self.root / f"{entry_id}.pk8"
        path.write_bytes(f"identity:{entry_id}".encode())
        entry = Entry(entry_id, str(path))
        self.held[entry_id] = entry
        return entry

    def entries(self, *, folder):
        return list(self.held.values())

    def find(self, entry_id, *, folder):
        return self.held.get(entry_id)

    def destinations(self, entry, trainer):
        return {game: {"ok": game != self.refuse, "reason": "Refused", "home_tracker": ""}
                for game in DEFAULT_CONFIG["trainers"]}

    def offer(self, entry, game, trainer):
        if game == self.refuse:
            raise ValueError("PKHeX refused this destination")
        path = self.root / f"converted-{entry.id}.{game}"
        path.write_bytes(Path(entry.path).read_bytes())
        return {"bank": entry.id, "file": str(path), "summary": entry.summary,
                "species": 25, "shiny": False, "legal": True, "home_tracker": ""}

    def remove(self, entry_id, *, folder):
        if entry_id == self.remove_error:
            raise OSError("Bank disk is not writable")
        self.removed.append(entry_id)
        entry = self.held.pop(entry_id, None)
        if entry is not None:
            Path(entry.path).unlink()

    def TradeSession(self, offers, *, folder):
        ids = tuple(offer.get("bank", "") for offer in offers)
        self.snapshots.append(ids)
        bank = self

        class Session:
            completed = 0

            def advance(self, count):
                if type(count) is not int or count < 0:
                    raise ValueError("Nonnegative integer required")
                for index in range(self.completed, min(count, len(ids))):
                    if ids[index]:
                        bank.remove(ids[index], folder=folder)
                    self.completed = index + 1
                self.completed = max(self.completed, count)
                return self.completed
        return Session()

    def import_file(self, path, trainers, *, folder):
        self.imported_source = (str(path), Path(path).read_bytes(), trainers)
        items = [ImportedPokemon("Box 1, slot 1", "Pikachu", 25, False, "banked", "swsh", "Left its item behind"),
                 ImportedPokemon("Box 1, slot 2", "Pikachu", 25, False, "already", "swsh", ""),
                 ImportedPokemon("Box 1, slot 3", "Invalid", 0, False, "refused", "", "Bad record")]
        return types.SimpleNamespace(name=Path(path).name, save="Sword, RICK", pokemon=items,
                                     count=lambda state: sum(item.state == state for item in items))


def trades_done(line):
    match = re.fullmatch(r"\[done\] trade (\d+) complete", line.strip())
    return int(match.group(1)) if match else None


class BankEngineTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.bank = FakeBank(self.root)
        self.bank.add("first")
        self.bank.add("second")
        self.bank.add("unrelated")
        self.received = types.SimpleNamespace(trades_done=trades_done)
        self.pokemon = types.SimpleNamespace(SERVICE=types.SimpleNamespace(
            make=lambda *a, **kw: {"file": str(self.root / "filler.pk3")},
            check=lambda game, path: {"legal": True, "species_id": 25}))
        self.config = copy.deepcopy(DEFAULT_CONFIG)
        self.config["prod_keys"] = str(self.root / "keys")
        self.engine = self.new_engine()
        self.token = "a" * 32
        self.addCleanup(self.close_log)

    def new_engine(self):
        return BankEngine(self.bank, self.received, self.pokemon, self.root, self.root / "backend", self.root / "python")

    def close_log(self):
        if self.engine.active is not None:
            self.engine.active["log"].close()

    def begin(self, ids=None, game="swsh", token=None):
        result = self.engine.dispatch("begin", {"token": token or self.token, "game": game,
            "ids": ids or ["second", "first"], "config": self.config, "version": "leafgreen"})
        # Hosts may save offers before confirmation. Fixtures intentionally do too.
        record = self.engine.active["receipt"]
        base = Path(result["received"])
        for number in range(1, 7):
            if game == "bdsp":
                path = base.with_name(f"{base.stem}_{number}.pb8")
            elif game == "frlg" and record["receive_trades"] > 1:
                path = base.with_name(f"{base.stem}_trade{number}_Pikachu.pk3")
            else:
                path = base if number == 1 else base.with_name(f"{base.stem}-{number}{base.suffix}")
            path.write_bytes(f"received-{number}".encode())
        return result

    def append(self, text, token=None):
        with (self.root / "logs" / f"bank-{token or self.token}.log").open("ab") as log:
            log.write(text.encode())

    def test_prepare_preserves_records_and_identity_in_requested_order(self):
        result = self.begin()
        self.assertEqual(self.bank.snapshots, [("second", "first")])
        self.assertEqual(self.bank.removed, [])
        self.assertEqual([item["bank"] for item in result["offers"]], ["second", "first"])
        self.assertEqual(Path(result["offers"][0]["file"]).read_bytes(), b"identity:second")
        self.assertNotIn("--fresh-pid", result["cmd"])
        self.assertNotIn("--code", result["cmd"])

    def test_cancel_prepared_run_keeps_all_records(self):
        self.begin()
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["completed"], 0)
        self.assertEqual(self.bank.removed, [])
        self.assertEqual(self.engine.pending(), [])

    def test_only_complete_lines_count_and_repeated_or_older_counts_are_harmless(self):
        self.begin()
        self.append("trade queued\n[done] trade -1 complete\n[done] trade 1 comp")
        self.assertEqual(self.engine.progress(self.token)["completed"], 0)
        self.append("lete\n[done] trade 1 complete\n[done] trade 0 complete\n")
        self.assertEqual(self.engine.progress(self.token)["completed"], 1)
        self.assertEqual(self.bank.removed, ["second"])
        self.assertIn("first", self.bank.held)

    def test_skipped_counts_and_counts_beyond_queue_never_remove_other_records(self):
        self.begin()
        self.append("[done] trade 5 complete\n")
        self.assertEqual(self.engine.progress(self.token)["completed"], 5)
        self.assertEqual(self.bank.removed, ["second", "first"])
        self.assertIn("unrelated", self.bank.held)

    def test_oversized_line_cannot_turn_its_suffix_into_a_confirmation(self):
        self.begin()
        self.append("x" * 131073)
        self.engine.progress(self.token)
        self.append("[done] trade 1 complete\n")
        self.assertEqual(self.engine.progress(self.token)["completed"], 0)
        self.assertEqual(self.bank.removed, [])
        self.append("[done] trade 1 complete\n")
        self.assertEqual(self.engine.progress(self.token)["completed"], 1)

    def test_stop_drains_final_events_and_preserves_uncompleted_records(self):
        self.begin()
        self.append("[done] trade 1 complete\n")
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["completed"], 1)
        self.assertIn("first", self.bank.held)
        self.assertIn("unrelated", self.bank.held)
        self.assertIsNone(self.engine.active)

    def test_exit_without_confirmed_event_does_not_remove_anything(self):
        self.begin()
        self.append("queued trade 1\nsession exited with code 0\n")
        self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(self.bank.removed, [])
        self.assertEqual(self.bank.deposited, [])

    def test_only_confirmed_received_records_are_inspected_and_banked_once(self):
        self.begin()
        self.engine.progress(self.token)
        self.assertEqual(self.bank.deposited, [])
        self.append("[done] trade 1 complete\n")
        result = self.engine.progress(self.token)
        self.assertEqual(result["received_count"], 1)
        self.assertEqual(result["received_entries"][0]["id"], "incoming-1")
        self.assertEqual(Path(self.bank.deposited[0][1]).read_bytes(), b"received-1")
        self.append("[done] trade 1 complete\n[done] trade 0 complete\n")
        self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(len(self.bank.deposited), 1)

    def test_received_legality_warning_is_preserved_without_rebuilding_the_record(self):
        result = self.begin()
        source = Path(result["received"])
        self.pokemon.SERVICE.check = lambda game, path: {"legal": False, "report": "Unusual record"}
        self.append("[done] trade 1 complete\n")
        result = self.engine.dispatch("end", {"token": self.token})
        entry = result["received_entries"][0]
        self.assertFalse(entry["legal"])
        self.assertEqual(Path(entry["path"]).read_bytes(), source.read_bytes())

    def test_skipped_counts_bank_all_confirmed_records_including_generated_extra_trades(self):
        self.begin()
        self.append("[done] trade 3 complete\n")
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["received_count"], 3)
        self.assertEqual(self.bank.removed, ["second", "first"])

    def test_each_game_resolves_native_received_names_after_confirmation(self):
        for index, game in enumerate(("za", "swsh", "bdsp", "frlg"), 1):
            with self.subTest(game=game):
                self.begin(["unrelated"], game=game, token=str(index) * 32)
                token = self.engine.active["receipt"]["token"]
                self.append("[done] trade 1 complete\n", token=token)
                result = self.engine.dispatch("end", {"token": token})
                self.assertEqual(result["received_count"] + result["received_already"], 1)
                self.bank.add("unrelated")

    def test_frlg_multi_trade_waits_for_exit_files_and_banks_only_completed_slot(self):
        result = self.begin(game="frlg")
        record = self.engine.active["receipt"]
        first = self.engine._incoming_path(record, 1)
        first.unlink()
        self.append("[done] trade 1 complete\n")
        self.assertEqual(self.engine.progress(self.token)["received_count"], 0)
        with self.assertRaisesRegex(ValueError, "confirmed trade 1 is missing"):
            self.engine.dispatch("end", {"token": self.token})
        first.write_bytes(b"late FRLG received")
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["received_count"], 1)
        self.assertIn("first", self.bank.held)

    def test_failed_deposit_retries_after_completion_line_was_consumed(self):
        self.begin()
        self.append("[done] trade 1 complete\n")
        self.bank.deposit_error = "Bank disk full"
        with self.assertRaisesRegex(OSError, "disk full"):
            self.engine.progress(self.token)
        self.bank.deposit_error = None
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["received_count"], 1)
        self.assertEqual(self.bank.removed, ["second"])

    def test_recovery_does_not_rebank_received_record_that_has_since_left_bank(self):
        self.begin()
        self.append("[done] trade 1 complete\n")
        self.engine.progress(self.token)
        self.bank.remove("incoming-1", folder=self.engine.folder)
        self.engine.active["log"].close()
        self.engine = self.new_engine()
        result = self.engine.dispatch("recover", {"token": self.token, "confirm_stopped": True})
        self.assertEqual(result["received_count"], 1)
        self.assertEqual(len(self.bank.deposited), 1)
        self.assertNotIn("incoming-1", self.bank.held)

    def test_existing_bank_bytes_are_not_duplicated(self):
        result = self.begin()
        Path(result["received"]).write_bytes(Path(self.bank.held["unrelated"].path).read_bytes())
        self.append("[done] trade 1 complete\n")
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["received_count"], 0)
        self.assertEqual(result["received_already"], 1)

    def test_receipt_failure_after_deposit_retries_journal_without_second_deposit(self):
        self.begin()
        self.append("[done] trade 1 complete\n")
        original = self.engine._save

        def save():
            if self.bank.deposited:
                with patch("bank_backend.os.replace", side_effect=OSError("receipt disk full")):
                    original()
            else:
                original()
        with patch.object(self.engine, "_save", side_effect=save):
            with self.assertRaisesRegex(OSError, "receipt disk full"):
                self.engine.progress(self.token)
        self.assertEqual(len(self.bank.deposited), 1)
        self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(len(self.bank.deposited), 1)
        record = json.loads(self.engine._receipt_path(self.token).read_text())
        self.assertEqual(record["incoming"]["1"]["entry"]["id"], "incoming-1")

    def test_regular_builder_session_uses_unique_outputs_without_outgoing_bank_ids(self):
        original = ["python", "swsh_host.py", "--received", "old.pk8", "--offer-file", "built.pk8"]
        result = self.engine.dispatch("watch", {"token": self.token, "game": "swsh",
                    "cmd": original, "offers": [{"file": "built.pk8", "bank": "unrelated"}]})
        self.assertEqual(self.bank.snapshots, [("",)])
        self.assertEqual(original[3], "old.pk8")
        self.assertEqual(result["cmd"][3], result["received"])
        Path(result["received"]).write_bytes(b"retail original")
        self.append("[done] trade 1 complete\n")
        result = self.engine.dispatch("end", {"token": self.token})
        self.assertEqual(result["received_count"], 1)
        self.assertEqual(self.bank.removed, [])

    def test_failed_removal_retries_consumed_and_buffered_completion_lines(self):
        self.begin()
        self.bank.remove_error = "second"
        self.append("[done] trade 1 complete\n[done] trade 2 complete\n")
        with self.assertRaises(OSError):
            self.engine.progress(self.token)
        self.assertEqual(self.bank.removed, [])
        self.bank.remove_error = None
        self.assertEqual(self.engine.progress(self.token)["completed"], 2)
        self.assertEqual(self.bank.removed, ["second", "first"])

    def test_old_callbacks_cannot_touch_a_new_run(self):
        self.begin()
        self.engine.dispatch("end", {"token": self.token})
        new_token = "b" * 32
        self.begin(["unrelated"], token=new_token)
        self.append("[done] trade 1 complete\n", token=new_token)
        for action in ("progress", "end"):
            with self.subTest(action=action), self.assertRaisesRegex(ValueError, "old Bank run"):
                self.engine.dispatch(action, {"token": self.token})
        self.assertEqual(self.bank.removed, [])
        self.assertEqual(self.engine.progress(new_token)["completed"], 1)
        self.assertEqual(self.bank.removed, ["unrelated"])

    def test_unfinished_receipt_blocks_new_preparation_until_explicit_recovery(self):
        self.begin()
        self.append("[done] trade 1 complete\n")
        self.engine.active["log"].close()
        self.engine = self.new_engine()  # Worker restart; receipt survives.
        with self.assertRaisesRegex(ValueError, "reconcile"):
            self.begin(["unrelated"], token="b" * 32)
        with self.assertRaisesRegex(ValueError, "Confirm"):
            self.engine.dispatch("recover", {"token": self.token})
        result = self.engine.dispatch("recover", {"token": self.token, "confirm_stopped": True})
        self.assertEqual(result["completed"], 1)
        self.assertEqual(self.bank.removed, ["second"])
        self.assertEqual(self.engine.pending(), [])
        self.begin(["unrelated"], token="b" * 32)

    def test_recovery_and_end_refuse_a_live_host(self):
        self.begin()
        self.engine.dispatch("attach", {"token": self.token, "pid": os.getpid()})
        self.append("[done] trade 1 complete\n")
        with patch("bank_backend.host_alive", return_value=True):
            with self.assertRaisesRegex(ValueError, "still running"):
                self.engine.dispatch("end", {"token": self.token})
            self.engine.active["log"].close()
            self.engine = self.new_engine()
            with self.assertRaisesRegex(ValueError, "still running"):
                self.engine.dispatch("recover", {"token": self.token, "confirm_stopped": True})
        self.assertEqual(self.bank.removed, [])

    def test_failed_conversion_never_starts_a_run_or_removes_source(self):
        self.bank.refuse = "swsh"
        with self.assertRaisesRegex(ValueError, "PKHeX refused"):
            self.begin()
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.engine.pending(), [])
        self.assertEqual(self.bank.removed, [])

    def test_duplicate_and_overfull_queues_are_refused(self):
        for ids in (["first", "first"], [str(n) for n in range(7)]):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                self.begin(ids)
        self.assertEqual(self.bank.snapshots, [])

    def test_import_reports_partial_refusals_and_keeps_source_file(self):
        source = self.root / "main"
        source.write_bytes(b"original save")
        result = self.engine.dispatch("import", {"path": str(source), "trainers": self.config["trainers"]})
        self.assertEqual(source.read_bytes(), b"original save")
        self.assertEqual(result["counts"], {"banked": 1, "already": 1, "refused": 1})
        self.assertEqual([item["detail"] for item in result["details"]], ["Left its item behind", "Bad record"])

    def test_receipt_write_failure_does_not_leave_an_unusable_active_session(self):
        with patch.object(self.engine, "_save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.begin()
        self.assertIsNone(self.engine.active)
        self.assertEqual(self.bank.removed, [])

    def test_invalid_receipt_identifiers_cannot_escape_run_folder(self):
        with self.assertRaises(ValueError):
            self.engine.dispatch("recover", {"token": "../config"})

    def test_each_game_command_uses_native_flags_and_preserves_identity(self):
        for game, flag in (("za", "--trade-offer"), ("swsh", "--offer-file"), ("bdsp", "--offer")):
            with self.subTest(game=game):
                cmd = trade_command(self.root, self.root / "python", self.config, game,
                    [{"file": "one"}, {"file": "two"}], self.root / "received.pk8")
                self.assertEqual(cmd.count(flag), 2)
                self.assertLess(cmd.index("one"), cmd.index("two"))
                self.assertNotIn("--fresh-pid", cmd)
        cmd = trade_command(self.root, self.root / "python", self.config, "frlg",
            [{"file": "offer"}], self.root / "received.pk3", version="leafgreen", filler="filler")
        self.assertEqual(cmd[cmd.index("--slots") + 1], "1")
        self.assertEqual(cmd[cmd.index("--trades") + 1], "1")
        self.assertEqual(cmd[-2:], ["filler", "offer"])
        cmd = trade_command(self.root, self.root / "python", self.config, "frlg",
            [{"file": str(n)} for n in range(6)], self.root / "received.pk3")
        self.assertEqual(cmd[cmd.index("--slots") + 1], "0,1,2,3,4,5")
        self.assertEqual(cmd[cmd.index("--trades") + 1], "6")


if __name__ == "__main__":
    unittest.main()
