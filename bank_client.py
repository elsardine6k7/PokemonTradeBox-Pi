"""Serialized, bounded Bank RPC outside GTK; the worker runs in PokeLDN's venv."""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import threading
from pathlib import Path


class BankClient:
    def __init__(self, python, repo, app_dir, dispatch):
        self.python, self.repo, self.app_dir = Path(python), Path(repo), Path(app_dir)
        self.dispatch = dispatch
        self.requests = queue.Queue()
        self.proc = None
        self.lock = threading.Lock()
        self.closed = False
        self.sequence = 0
        self.cancel_epoch = 0
        self.thread = threading.Thread(target=self._work, daemon=True, name="tradebox-bank")
        self.thread.start()

    def submit(self, action, payload, callback, *, timeout=60):
        if self.closed:
            self.dispatch(callback, None, "Bank worker is closed.")
            return
        self.requests.put((action, payload, callback, timeout, self.cancel_epoch))

    def _start(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        self._stop()
        log_dir = self.app_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / "bank-worker.log").open("a", encoding="utf-8") as errors:
            proc = subprocess.Popen([str(self.python), str(self.app_dir / "bank_backend.py"),
                    "--repo", str(self.repo), "--app-dir", str(self.app_dir)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                text=True, encoding="utf-8", bufsize=1, start_new_session=os.name == "posix")
        replies = queue.Queue()

        def read():
            try:
                for line in proc.stdout:
                    replies.put(json.loads(line))
            except (ValueError, OSError) as exc:
                replies.put({"ok": False, "error": f"Invalid Bank worker response: {exc}"})
            finally:
                replies.put({"ok": False, "error": "Bank worker exited. Check logs/bank-worker.log and reconcile any unfinished Bank run."})
                proc.stdout.close()

        with self.lock:
            self.proc, self.replies = proc, replies
        threading.Thread(target=read, daemon=True, name="tradebox-bank-replies").start()

    def _stop(self):
        with self.lock:
            proc, self.proc = self.proc, None
        if proc is None:
            return
        # This group contains only the Bank worker and its PKHeX helper, never
        # a trade launcher. SessionControl remains the launcher's sole owner.
        try:
            if os.name == "posix":
                os.killpg(proc.pid, signal.SIGTERM)
            elif proc.poll() is None:
                proc.terminate()
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            try:
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)
        if proc.stdin:
            proc.stdin.close()

    def _work(self):
        while (request := self.requests.get()) is not None:
            action, payload, callback, timeout, epoch = request
            result, error = None, ""
            try:
                if self.closed:
                    raise ValueError("Bank worker is closed.")
                if epoch != self.cancel_epoch:
                    raise ValueError("Bank work cancelled. Refresh the Bank; imports may be partial.")
                self._start()
                if epoch != self.cancel_epoch:
                    self._stop()
                    raise ValueError("Bank work cancelled. Refresh the Bank; imports may be partial.")
                self.sequence += 1
                proc = self.proc
                proc.stdin.write(json.dumps({"id": self.sequence, "action": action, "payload": payload}) + "\n")
                proc.stdin.flush()
                reply = self.replies.get(timeout=timeout)
                if epoch != self.cancel_epoch:
                    self._stop()
                    raise ValueError("Bank work cancelled. Refresh the Bank; imports may be partial.")
                if reply.get("id") not in (None, self.sequence):
                    raise ValueError("Bank worker response belongs to a different request.")
                if not reply.get("ok"):
                    if reply.get("id") is None:
                        self._stop()
                    raise ValueError(reply.get("error", "Bank operation failed."))
                result = reply["result"]
            except queue.Empty:
                self._stop()
                error = "Bank operation timed out. Imports may be partial; refresh the list. Stop any Bank host and reconcile its run before hosting again."
            except Exception as exc:
                error = str(exc)
            self.dispatch(callback, result, error)
        self._stop()

    def cancel(self):
        # Called off GTK via a short-lived thread; Bank UI disallows this during
        # a live trade, completion processing, or recovery.
        self.cancel_epoch += 1
        threading.Thread(target=self._stop, daemon=True).start()

    def close(self):
        self.closed = True
        self.requests.put(None)
        self.cancel()
