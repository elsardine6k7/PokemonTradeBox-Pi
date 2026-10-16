"""Real Bank worker IPC and lock/timeout checks, run by Ubuntu CI."""
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from bank_client import BankClient
from test_startup_checks import fake_backend


@unittest.skipUnless(os.name == "posix", "Bank worker locks require the Pi's POSIX environment")
class BankClientTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.repo = self.root / "backend"
        fake_backend(self.repo, version="0.24.0", api=(1, 4))
        source = Path(__file__).resolve().parents[1]
        shutil.copyfile(source / "bank_backend.py", self.root / "bank_backend.py")
        app = self.repo / "pokeldn/app"
        app.mkdir(exist_ok=True)
        (app / "__init__.py").touch()
        (app / "bank.py").write_text(
            f"import sys\nsys.path.insert(0, {str(source)!r})\nsys.path.insert(0, {str(source / 'tests')!r})\n"
            "from test_bank import FakeBank\nfrom pathlib import Path\n"
            "api = FakeBank(Path(__file__).resolve().parents[2])\n"
            "entries = api.entries\nfind = api.find\nimport_file = api.import_file\n"
            "destinations = api.destinations\noffer = api.offer\nremove = api.remove\nTradeSession = api.TradeSession\ndeposit = api.deposit\n",
            encoding="utf-8")
        (app / "received.py").write_text("from test_bank import trades_done\n", encoding="utf-8")
        self.clients = []
        self.addCleanup(self.close_clients)

    def close_clients(self):
        for client, _replies in self.clients:
            client.close()
        for client, _replies in self.clients:
            client.thread.join(timeout=8)

    def client(self):
        replies = queue.Queue()
        client = BankClient(Path(sys.executable), self.repo, self.root,
                            lambda callback, result, error: replies.put((callback, result, error)))
        self.clients.append((client, replies))
        return client, replies

    def request(self, client_and_replies, action, payload=None, timeout=5):
        client, replies = client_and_replies
        callback = lambda *_: None
        client.submit(action, payload or {}, callback, timeout=timeout)
        returned, result, error = replies.get(timeout=10)
        self.assertIs(returned, callback)
        return result, error

    def test_real_worker_lists_and_imports_without_changing_the_source(self):
        client = self.client()
        result, error = self.request(client, "list")
        self.assertEqual(error, "")
        self.assertEqual(result, {"entries": [], "pending": []})
        source = self.root / "save.dat"
        source.write_bytes(b"original save")
        result, error = self.request(client, "import", {"path": str(source), "trainers": {}})
        self.assertEqual(error, "")
        self.assertEqual(result["counts"]["banked"], 1)
        self.assertEqual(source.read_bytes(), b"original save")

    def test_second_worker_cannot_write_the_same_bank(self):
        first = self.client()
        self.assertEqual(self.request(first, "list")[1], "")
        second = self.client()
        result, error = self.request(second, "list")
        self.assertIsNone(result)
        self.assertIn("Another TradeBox", error)
        self.assertEqual(self.request(first, "list")[1], "")

    def test_real_worker_banks_only_confirmed_received_file(self):
        with (self.repo / "pokeldn/pokemon.py").open("a", encoding="utf-8") as file:
            file.write("\nSERVICE.check = lambda game, path: {'legal': True}\n")
        client = self.client()
        token = "a" * 32
        result, error = self.request(client, "watch", {"token": token, "game": "swsh",
            "offers": [{"file": "built.pk8"}], "cmd": ["host", "--received", "old.pk8"]})
        self.assertEqual(error, "")
        Path(result["received"]).write_bytes(b"retail Pokemon bytes")
        result, error = self.request(client, "progress", {"token": token})
        self.assertEqual(result["received_count"], 0)
        (self.root / "logs" / f"bank-{token}.log").write_text("[done] trade 1 complete\n")
        result, error = self.request(client, "end", {"token": token})
        self.assertEqual(error, "")
        self.assertEqual(result["received_count"], 1)
        result, error = self.request(client, "list")
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(Path(result["entries"][0]["path"]).read_bytes(), b"retail Pokemon bytes")

    def test_timeout_stops_only_the_bank_worker_group(self):
        with (self.repo / "pokeldn/app/bank.py").open("a", encoding="utf-8") as file:
            file.write("\nimport time\ndef entries(*a, **kw): time.sleep(30); return []\n")
        unrelated = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            started = time.monotonic()
            result, error = self.request(self.client(), "list", timeout=.3)
            self.assertIsNone(result)
            self.assertIn("timed out", error)
            self.assertLess(time.monotonic() - started, 6)
            self.assertIsNone(unrelated.poll())
        finally:
            unrelated.terminate()
            unrelated.wait(timeout=5)

    def test_cancellation_unblocks_a_request_and_keeps_the_client_usable(self):
        with (self.repo / "pokeldn/app/bank.py").open("a", encoding="utf-8") as file:
            file.write("\nimport time\ndef entries(*a, **kw): time.sleep(30); return []\n")
        client, replies = self.client()
        client.submit("list", {}, lambda *_: None)
        client.cancel()
        _callback, result, error = replies.get(timeout=8)
        self.assertIsNone(result)
        self.assertTrue(error)
        # An API-level refusal after cancellation is returned, not a hung RPC.
        result, error = self.request((client, replies), "details", {"id": "missing", "trainer": {}, "game": "swsh"})
        self.assertIsNone(result)
        self.assertIn("no longer", error)


if __name__ == "__main__":
    unittest.main()
