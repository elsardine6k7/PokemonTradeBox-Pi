"""Bank API 1.4 worker. JSON requests arrive on stdin; replies leave on stdout.

Runs in PokeLDN's venv. Only documented Bank APIs touch Bank records; TradeBox
owns its queue, run receipts, logs, and launcher lifecycle.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from contextlib import redirect_stdout
from dataclasses import asdict
from pathlib import Path


GAMES = {"za": "Legends Z-A", "swsh": "Sword / Shield", "bdsp": "BDSP", "frlg": "FireRed / LeafGreen"}
EXTENSIONS = {"za": "pa9", "swsh": "pk8", "bdsp": "pb8", "frlg": "pk3"}


def trade_command(repo, python, config, game, offers, received, *, version="firered", filler=None):
    """Preserve the banked records' identities: never pass --fresh-pid."""
    trainer = config["trainers"][game]
    base = [str(python), "-u"]
    keys = ["--keys", str(config["prod_keys"])]
    files = [str(item["file"]) for item in offers]
    if game == "za":
        cmd = base + [str(repo / "bin/za_host.py"), *keys, "--trainer-name", trainer["ot"],
                      "--offer-out", str(received), "--seconds", "900"]
        for path in files:
            cmd += ["--trade-offer", path]
    elif game == "swsh":
        cmd = base + [str(repo / "bin/swsh_host.py"), *keys, "--trainer-name", trainer["ot"],
            "--trainer-tid", str(trainer["tid"]), "--trainer-sid", str(trainer["sid"]),
            "--received", str(received), "--seconds", "900"]
        for path in files:
            cmd += ["--offer-file", path]
    elif game == "bdsp":
        cmd = base + [str(repo / "bin/bdsp_host.py"), *keys, "--name", trainer["ot"],
            "--trainer", f"{trainer['ot']}:{trainer['tid']}:{trainer['sid']}",
            "--language", str(trainer["language"]), "--complete-trade",
            "--save-theirs", str(received.with_suffix("")), "--seconds", "900"]
        for path in files:
            cmd += ["--offer", path]
    elif game == "frlg":
        # Direct Corner requires two party members. The filler is never offered.
        party = ([str(filler)] + files) if len(files) == 1 else files
        first = 1 if len(files) == 1 else 0
        cmd = base + [str(repo / "bin/frlg_trade_host.py"), *keys, "--ot", trainer["ot"],
            "--version", version, "--id", f"{trainer['tid']}:{trainer['sid']}",
            "--slot", str(first), "--slots", ",".join(str(n) for n in range(first, first + len(files))),
            "--trades", str(len(files)), "-o", str(received), *party]
    else:
        raise ValueError("Unsupported Bank destination.")
    return cmd


def process_birth(pid):
    """Linux process identity, used only to refuse recovery while its host lives."""
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except (OSError, ValueError, IndexError):
        return None


def host_alive(receipt):
    pid = receipt.get("pid")
    if not pid:
        return False
    birth = process_birth(pid)
    if birth is not None:
        return receipt.get("birth") in (None, birth)
    if os.name == "posix":
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    return False


class BankEngine:
    def __init__(self, bank, received, pokemon, app_dir, repo, python):
        self.bank, self.received, self.pokemon = bank, received, pokemon
        self.app_dir, self.repo, self.python = Path(app_dir), Path(repo), Path(python)
        self.folder = self.app_dir / "bank"
        self.data_dir = self.app_dir / "bank-data"
        self.run_dir = self.data_dir / "runs"
        self.active = None

    def _entry(self, entry_id):
        entry = self.bank.find(entry_id, folder=self.folder)
        if entry is None:
            raise ValueError("This Pokemon is no longer in the Bank. Refresh the list.")
        return entry

    def _receipt_path(self, token):
        if not isinstance(token, str) or re.fullmatch(r"[0-9a-f]{32}", token) is None:
            raise ValueError("Invalid Bank run identifier.")
        return self.run_dir / f"{token}.json"

    def _save(self):
        self.active["dirty"] = True
        record = self.active["receipt"]
        path = self._receipt_path(record["token"])
        self.run_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(tmp, path)
        self.active["dirty"] = False

    def pending(self):
        pending = []
        for path in sorted(self.run_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("state") != "finished":
                    pending.append({"token": record["token"], "game": record["game"],
                                    "pid": record.get("pid"), "live": host_alive(record)})
            except (OSError, ValueError, KeyError, AttributeError, TypeError):
                raise ValueError(f"Cannot read Bank run receipt {path.name}. Repair it before hosting.") from None
        return pending

    def _idle(self):
        if self.active is not None or self.pending():
            raise ValueError("Finish or reconcile the previous Bank run before changing the Bank.")

    def _require_run(self, token):
        if self.active is None or self.active["receipt"]["token"] != token:
            raise ValueError("This callback belongs to an old Bank run; it was ignored.")
        return self.active

    def _open_run(self, receipt):
        log = self.app_dir / "logs" / f"bank-{receipt['token']}.log"
        self.active = {"receipt": receipt,
                       "session": self.bank.TradeSession(receipt["offers"], folder=self.folder),
                       "log": log.open("rb"), "buffer": b"", "dropping": False, "seen": 0}

    def _incoming_path(self, receipt, number):
        base = Path(receipt["received"])
        game = receipt["game"]
        if game == "bdsp":
            return base.with_name(f"{base.stem}_{number}.pb8")
        if game == "frlg" and receipt.get("receive_trades", 1) > 1:
            matches = list(base.parent.glob(f"{base.stem}_trade{number}_*.pk3"))
            if len(matches) > 1:
                raise ValueError(f"Multiple received files for trade {number}; check this run's files.")
            return matches[0] if matches else None
        return base if number == 1 else base.with_name(f"{base.stem}-{number}{base.suffix}")

    def _deposit_received(self, run, *, final=False):
        record = run["receipt"]
        if not record.get("received"):  # Receipts made before automatic banking.
            return
        incoming = record.setdefault("incoming", {})
        for number in range(1, run["session"].completed + 1):
            if str(number) in incoming:
                continue
            path = self._incoming_path(record, number)
            if path is None or not path.is_file():
                # FR/LG writes its files during shutdown, after the done lines.
                if final:
                    raise ValueError(f"Received file for confirmed trade {number} is missing. Check received-bank, then retry Bank finish.")
                continue
            info = self.pokemon.SERVICE.check(record["game"], str(path))
            entry = self.bank.deposit(record["game"], str(path), info, folder=self.folder)
            incoming[str(number)] = {"state": "banked" if entry else "already",
                                     "entry": asdict(entry) if entry else None}
            self._save()

    def _result(self, receipt):
        incoming = list(receipt.get("incoming", {}).values())
        return {"token": receipt["token"], "completed": receipt["completed"],
                "total": len(receipt["offers"]),
                "received_count": sum(item["state"] == "banked" for item in incoming),
                "received_already": sum(item["state"] == "already" for item in incoming),
                "received_entries": [item["entry"] for item in incoming if item["entry"]]}

    def progress(self, token, *, final=False):
        run = self._require_run(token)
        # Retry a previously observed count even if an OSError consumed its line.
        run["session"].advance(run["seen"])
        while True:
            while b"\n" in run["buffer"]:
                line, run["buffer"] = run["buffer"].split(b"\n", 1)
                if run["dropping"] or len(line) > 65536:
                    run["dropping"] = False
                    continue
                count = self.received.trades_done(line.decode("utf-8", errors="replace"))
                if count is not None:
                    run["seen"] = max(run["seen"], count)
                    run["session"].advance(run["seen"])
            if len(run["buffer"]) > 65536:
                run["buffer"] = b""  # An oversized/non-line payload is not a completion event.
                run["dropping"] = True
            chunk = run["log"].read(65536)
            if not chunk:
                break
            run["buffer"] += chunk
        completed = run["session"].completed
        previous = run["receipt"]["completed"]
        if completed != previous:
            run["receipt"]["completed"] = completed
            try:
                self._save()
            except Exception:
                run["receipt"]["completed"] = previous
                raise
        self._deposit_received(run, final=final)
        # Also retry receipt writes after a deposit succeeded but its save failed.
        if run.get("dirty"):
            self._save()
        return self._result(run["receipt"])

    def dispatch(self, action, payload):
        if action == "list":
            return {"entries": [asdict(entry) for entry in self.bank.entries(folder=self.folder)],
                    "pending": self.pending()}
        if action == "import":
            self._idle()
            result = self.bank.import_file(payload["path"], payload["trainers"], folder=self.folder)
            return {"name": result.name, "save": result.save,
                    "counts": {state: result.count(state) for state in ("banked", "already", "refused")},
                    "details": [asdict(item) for item in result.pokemon if item.detail][:30]}
        if action == "details":
            self._idle()
            entry = self._entry(payload["id"])
            routes = self.bank.destinations(entry, payload["trainer"])
            return {"entry": asdict(entry), "route": routes.get(payload["game"],
                    {"ok": False, "reason": "No supported conversion for this game."})}
        if action == "remove":
            self._idle()
            entry = self._entry(payload["id"])
            self.bank.remove(entry.id, folder=self.folder)
            return {}
        if action in ("begin", "watch"):
            self._idle()
            token, game = payload["token"], payload["game"]
            self._receipt_path(token)
            if game not in GAMES:
                raise ValueError("Unsupported Bank game.")
            received = self.app_dir / "received-bank" / f"{token}.{EXTENSIONS[game]}"
            received.parent.mkdir(parents=True, exist_ok=True)
            if action == "begin":
                ids = payload["ids"]
                if not 1 <= len(ids) <= 6 or len(ids) != len(set(ids)):
                    raise ValueError("Queue one to six different Bank records for a supported game.")
                config = payload["config"]
                trainer = config["trainers"][game]
                offers = [self.bank.offer(self._entry(entry_id), game, trainer) for entry_id in ids]
                if any(not item.get("legal") for item in offers):
                    raise ValueError("PKHeX refused a legal conversion for one of the queued Pokemon.")
                filler = None
                if game == "frlg" and len(offers) == 1:
                    filler = self.pokemon.SERVICE.make("frlg", 25, trainer, level=5, shiny=False)["file"]
                cmd = trade_command(self.repo, self.python, config, game, offers, received,
                                    version=payload.get("version", "firered"), filler=filler)
                receive_trades = len(offers)
            else:
                # Regular builder trades have no outgoing Bank IDs to remove.
                offers = [{"file": str(item["file"])} for item in payload["offers"]]
                cmd = [str(arg) for arg in payload["cmd"]]
                flag = {"za": "--offer-out", "swsh": "--received", "bdsp": "--save-theirs", "frlg": "-o"}[game]
                cmd[cmd.index(flag) + 1] = str(received.with_suffix("") if game == "bdsp" else received)
                receive_trades = int(cmd[cmd.index("--trades") + 1]) if "--trades" in cmd else 1
            log = self.app_dir / "logs" / f"bank-{token}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.touch(exist_ok=False)
            receipt = {"token": token, "game": game, "offers": offers, "state": "running",
                       "completed": 0, "pid": None, "birth": None, "received": str(received),
                       "receive_trades": receive_trades, "incoming": {}}
            try:
                self._open_run(receipt)
                self._save()
            except Exception:
                if self.active is not None:
                    self.active["log"].close()
                    self.active = None
                raise
            return {"token": token, "offers": offers, "cmd": cmd, "received": str(received)}
        if action == "attach":
            run = self._require_run(payload["token"])
            pid = payload["pid"]
            if type(pid) is not int or pid <= 0:
                raise ValueError("Invalid host PID.")
            run["receipt"].update(pid=pid, birth=process_birth(pid))
            self._save()
            return {}
        if action == "progress":
            return self.progress(payload["token"])
        if action == "end":
            if self.active is None:
                return self.dispatch("recover", payload)
            run = self._require_run(payload["token"])
            if host_alive(run["receipt"]):
                raise ValueError("The Bank host is still running. Stop it before finishing the Bank run.")
            result = self.progress(payload["token"], final=True)
            run["receipt"]["state"] = "finished"
            self._save()
            run["log"].close()
            self.active = None
            return result
        if action == "recover":
            if self.active is not None:
                raise ValueError("Stop and finish the current Bank run first.")
            record = json.loads(self._receipt_path(payload["token"]).read_text(encoding="utf-8"))
            if record["state"] == "finished":
                return self._result(record)
            if host_alive(record):
                raise ValueError("The old Bank host is still running. Stop it before reconciling.")
            if record.get("pid") is None and not payload.get("confirm_stopped"):
                raise ValueError("Confirm the interrupted host is stopped before reconciling its log.")
            self._open_run(record)
            return self.dispatch("end", {"token": record["token"]})
        raise ValueError("Unknown Bank request.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--app-dir", required=True, type=Path)
    args = parser.parse_args()
    args.repo = args.repo.expanduser().resolve()
    args.app_dir = args.app_dir.expanduser().resolve()
    os.environ["POKELDN_DATA"] = str(args.app_dir / "bank-data")
    sys.path.insert(0, str(args.repo))
    try:
        # flock is released by the OS if the worker crashes. Never share the
        # desktop Bank folder: this lock covers TradeBox's separate Bank only.
        import fcntl
        args.app_dir.joinpath("bank").mkdir(parents=True, exist_ok=True)
        lock = (args.app_dir / "bank" / ".tradebox.lock").open("a")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another TradeBox owns this Bank. Close it before opening this one.") from None
        with redirect_stdout(sys.stderr):
            from pokeldn import pokemon
            from pokeldn.plugins import API
            from pokeldn.app import bank, received
            if API.version != 1 or API.level < 4:
                raise ValueError("Bank requires PokeLDN v0.24.0+ and Program API 1.4.")
            engine = BankEngine(bank, received, pokemon, args.app_dir, args.repo, Path(sys.executable))
    except Exception as exc:
        print(json.dumps({"id": None, "ok": False, "error": str(exc)}), flush=True)
        return 1
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            request_id = request["id"]
            with redirect_stdout(sys.stderr):
                result = engine.dispatch(request["action"], request.get("payload", {}))
            reply = {"id": request_id, "ok": True, "result": result}
        except Exception as exc:
            reply = {"id": request_id, "ok": False, "error": str(exc)}
        print(json.dumps(reply), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
