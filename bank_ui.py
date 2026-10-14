"""Touchscreen Bank pages and launcher integration. No GTK import at module load."""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from bank_backend import GAMES
from bank_client import BankClient


def tracker_note(value):
    return {"empty": "HOME tracker warning: this conversion has no HOME-issued tracker.",
            "made": "HOME tracker warning: this conversion uses a generated tracker."}.get(value, "")


class BankUI:
    def _init_bank(self, app_dir, gtk, glib):
        self._bank_dir, self._bank_gtk, self._bank_glib = Path(app_dir), gtk, glib
        self._bank_client = None
        self._bank_config = None
        self._bank_available = False
        self._bank_busy = False
        self._bank_run = None
        self._bank_finish_pending = False
        self.bank_entries, self.bank_queue, self.bank_pending = [], [], []
        self.bank_game, self.bank_version = "za", "firered"
        self.bank_page = 0
        self._bank_search = ""

    def _configure_bank(self, config, available):
        self._bank_shutdown()
        self._bank_config, self._bank_available = config, available
        self.bank_version = config["frlg_version"]
        self.bank_entries, self.bank_queue, self.bank_pending = [], [], []

    def _bank_shutdown(self):
        if self._bank_client is not None:
            self._bank_client.close()
            self._bank_client = None

    def _bank_rpc(self, action, payload, callback, *, timeout=60):
        if self._bank_client is None:
            repo = Path(self._bank_config["pokeldn_repo"])
            self._bank_client = BankClient(repo / ".venv/bin/python", repo, self._bank_dir,
                                           self._bank_glib.idle_add)
        self._bank_client.submit(action, payload, callback, timeout=timeout)

    def _bank_editable(self):
        if self._bank_busy or self._bank_run is not None or self.session_control.busy or (
                self.proc is not None and self.proc.poll() is None):
            self.set_status("Finish the Bank operation or trade before changing the Bank queue.")
            return False
        return True

    def _bank_action(self, action, payload, callback, *, timeout=60):
        if not self._bank_available or not self._bank_editable():
            return False
        self._bank_busy = True
        self.set_status("Working on the Bank...")

        def done(result, error):
            self._bank_busy = False
            if error:
                self.set_status(f"Bank: {error}")
                self.show_bank()
            else:
                callback(result)
            return False

        self._bank_rpc(action, payload, done, timeout=timeout)
        return True

    def _bank_button(self, label, callback, *, enabled=True):
        button = self.button(label, callback)
        button.set_vexpand(False)
        button.set_size_request(-1, 44)
        button.set_sensitive(enabled)
        return button

    def _bank_text(self, text):
        from gi.repository import Pango
        label = self._bank_gtk.Label(label=text, xalign=0)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_selectable(True)
        return label

    def show_bank(self, *_):
        Gtk = self._bank_gtk
        box = self.page("POKEMON BANK", self.show_home)
        if not self._bank_available:
            box.append(self._bank_text("Bank needs PokeLDN v0.24.0+ and stable API 1.4. Update PokeLDN, then rerun startup checks in Settings."))
            self.win.set_child(box)
            return
        available = self._bank_editable_silent()
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        toolbar.append(self._bank_button("IMPORT FILE / SAVE", self.bank_choose_import, enabled=available))
        toolbar.append(self._bank_button("REFRESH", self.bank_refresh, enabled=available))
        toolbar.append(self._bank_button(f"QUEUE ({len(self.bank_queue)}/6)", self.show_bank_queue))
        box.append(toolbar)
        box.append(self._bank_button(f"TRADE INTO: {self._bank_target_name()}", self.bank_choose_game, enabled=available))
        if self._bank_busy:
            box.append(self._bank_button("CANCEL BANK WORK", self.bank_cancel_work))
        if self._bank_run is not None and self._bank_run.get("error"):
            box.append(self._bank_button("RETRY BANK FINISH", self.bank_retry_finish))
        search = Gtk.Entry(placeholder_text="Search saved Pokemon")
        search.set_text(self._bank_search)
        search.connect("changed", lambda entry: self._bank_search_changed(entry))
        search.connect("activate", lambda *_: self.show_bank())
        box.append(search)
        box.append(self._bank_button("SEARCH", lambda *_: self.show_bank()))
        sc = self.touch_scrolled_window()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for pending in self.bank_pending:
            col.append(self._bank_text(f"Unfinished Bank run ({GAMES.get(pending['game'], pending['game'])}). Reconcile its confirmed trades before hosting again."))
            col.append(self._bank_button("RECONCILE FINISHED RUN", lambda *_, p=pending: self.bank_confirm_recover(p), enabled=available))
        found = [entry for entry in self.bank_entries if self._bank_search.casefold() in
                 f"{entry['summary']} {entry['game']}".casefold()]
        pages = max(1, (len(found) + 11) // 12)
        self.bank_page = min(self.bank_page, pages - 1)
        if not found:
            col.append(self._bank_text("No Pokemon to show. Import a Pokemon file or a game save to get started."))
        for entry in found[self.bank_page * 12:(self.bank_page + 1) * 12]:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            label = self._bank_text(f"{entry['summary']}\n{GAMES.get(entry['game'], entry['game'])} - {'Legal' if entry['legal'] else 'Legality warning'}")
            label.set_hexpand(True)
            row.append(label)
            row.append(self._bank_button("VIEW", lambda *_, e=entry: self.bank_details(e), enabled=available))
            col.append(row)
        sc.set_child(col)
        box.append(sc)
        nav = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        nav.append(self._bank_button("PREVIOUS", lambda *_: self._bank_turn_page(-1), enabled=self.bank_page > 0))
        nav.append(Gtk.Label(label=f"{self.bank_page + 1}/{pages} - {len(found)} Pokemon"))
        nav.append(self._bank_button("NEXT", lambda *_: self._bank_turn_page(1), enabled=self.bank_page < pages - 1))
        box.append(nav)
        self.win.set_child(box)

    def _bank_editable_silent(self):
        return (not self._bank_busy and self._bank_run is None and not self.session_control.busy
                and (self.proc is None or self.proc.poll() is not None))

    def _bank_target_name(self):
        return ("FireRed" if self.bank_version == "firered" else "LeafGreen") if self.bank_game == "frlg" else GAMES[self.bank_game]

    def _bank_search_changed(self, entry):
        text = entry.get_text()
        if text != self._bank_search:
            self._bank_search, self.bank_page = text, 0
            # Preserve keyboard focus by leaving the entry in place; refresh
            # the results explicitly when the user finishes typing.

    def _bank_turn_page(self, delta):
        self.bank_page = max(0, self.bank_page + delta)
        self.show_bank()

    def bank_refresh(self, *_):
        def ready(result):
            self.bank_entries, self.bank_pending = result["entries"], result["pending"]
            held = {entry["id"] for entry in self.bank_entries}
            self.bank_queue = [entry for entry in self.bank_queue if entry["id"] in held]
            self.set_status(f"Bank: {len(self.bank_entries)} Pokemon.")
            self.show_bank()
        if self._bank_action("list", {}, ready):
            self.show_bank()

    def bank_open(self, *_):
        self.show_bank()
        if self._bank_available and self._bank_editable_silent():
            self.bank_refresh()

    def bank_choose_game(self, *_):
        if not self._bank_editable():
            return
        box = self.page("BANK DESTINATION", self.show_bank)
        if self.bank_queue:
            box.append(self._bank_text("Clear the queue before changing its destination."))
        for game, label, version in (("za", GAMES["za"], "firered"), ("swsh", GAMES["swsh"], "firered"),
                ("bdsp", GAMES["bdsp"], "firered"), ("frlg", "FireRed", "firered"), ("frlg", "LeafGreen", "leafgreen")):
            box.append(self._bank_button(label, lambda *_, g=game, v=version: self.bank_set_game(g, v)))
        self.win.set_child(box)

    def bank_set_game(self, game, version):
        if not self._bank_editable():
            return
        if self.bank_queue and (game, version) != (self.bank_game, self.bank_version):
            self.set_status("Clear the Bank queue before changing its destination.")
            return
        self.bank_game, self.bank_version = game, version
        self.show_bank()

    def bank_choose_import(self, *_):
        if not self._bank_editable():
            return
        trainer = self._bank_config["trainers"][self.bank_game]
        box = self._bank_message("BANK IMPORT", "Your original file stays intact. PokeLDN keeps supported native records and converts older formats when possible.\n\nConfigured trainers are used for their games. Other games use your selected destination's trainer:\n"
            f"{self._bank_target_name()}: {trainer['ot']} - raw TID {trainer['tid']} / SID {trainer['sid']}", self.show_bank)
        box.append(self._bank_button("CHOOSE FILE / SAVE", self._bank_choose_file))

    def _bank_choose_file(self, *_):
        if not self._bank_editable():
            return
        Gtk = self._bank_gtk
        chooser = Gtk.FileChooserNative.new("Import a Pokemon file or game save", self.win,
                                            Gtk.FileChooserAction.OPEN, "Import", "Cancel")
        chooser.set_modal(True)
        self._bank_chooser = chooser

        def response(dialog, code):
            if code == Gtk.ResponseType.ACCEPT:
                file = dialog.get_file()
                path = file.get_path() if file is not None else None
                if path:
                    self.bank_import(path)
            dialog.destroy()
            self._bank_chooser = None
        chooser.connect("response", response)
        chooser.show()

    def bank_import(self, path):
        def ready(result):
            counts = result["counts"]
            text = f"{result['name']}\n{result['save']}\n\nAdded: {counts['banked']}\nAlready imported: {counts['already']}\nRefused: {counts['refused']}"
            for item in result["details"]:
                text += f"\n\n{item['where']} {item['species']} ({item['state']}): {item['detail']}"
            self._bank_message("IMPORT RESULTS", text, self.bank_open)
            self.set_status("Import finished. Source file preserved.")
        trainers = dict(self._bank_config["trainers"])
        for game in ("frlg", "lgpe", "swsh", "bdsp", "pla", "sv", "za"):
            trainers.setdefault(game, dict(trainers[self.bank_game]))
        if self._bank_action("import", {"path": str(path), "trainers": trainers}, ready, timeout=180):
            self.show_bank()

    def bank_cancel_work(self, *_):
        if self._bank_busy and self._bank_run is None and self._bank_client is not None:
            self._bank_client.cancel()
            self.set_status("Cancelling Bank work. Refresh afterwards; imports may be partial.")

    def _bank_message(self, title, text, back):
        box = self.page(title, back)
        sc = self.touch_scrolled_window()
        sc.set_vexpand(True)
        sc.set_child(self._bank_text(text))
        box.append(sc)
        self.win.set_child(box)
        return box

    def bank_details(self, entry):
        def ready(result):
            entry, route = result["entry"], result["route"]
            text = f"{entry['summary']}\nStored in: {GAMES.get(entry['game'], entry['game'])}\n{'Legal' if entry['legal'] else 'Legality warning'}\n\nTrade into {self._bank_target_name()}: {'Available' if route.get('ok') else route.get('reason', 'Unavailable')}"
            note = tracker_note(route.get("home_tracker"))
            if note:
                text += "\n\n" + note
            box = self._bank_message("BANK POKEMON", text, self.show_bank)
            box.append(self._bank_button("ADD TO QUEUE", lambda *_: self.bank_enqueue(entry), enabled=bool(route.get("ok"))))
            box.append(self._bank_button("DELETE BANK COPY", lambda *_: self.bank_confirm_remove(entry)))
        self._bank_action("details", {"id": entry["id"], "game": self.bank_game,
                                      "trainer": self._bank_config["trainers"][self.bank_game]}, ready)

    def bank_enqueue(self, entry):
        if not self._bank_editable():
            return
        if any(item["id"] == entry["id"] for item in self.bank_queue):
            self.set_status("This Pokemon is already queued.")
        elif len(self.bank_queue) >= 6:
            self.set_status("The Bank queue has six Pokemon. Remove one before adding another.")
        else:
            self.bank_queue.append(entry)
            self.set_status(f"Queued for {self._bank_target_name()}: {len(self.bank_queue)}/6.")
            self.show_bank()

    def bank_confirm_remove(self, entry):
        if not self._bank_editable():
            return
        if any(item["id"] == entry["id"] for item in self.bank_queue):
            self.set_status("Remove this Pokemon from the queue before deleting its Bank copy.")
            return
        box = self._bank_message("DELETE BANK COPY?", f"{entry['summary']}\n\nYour source file stays intact. PokeLDN remembers imports, so importing the same Pokemon again may report it as already imported.", self.show_bank)
        box.append(self._bank_button("YES - DELETE BANK COPY", lambda *_: self._bank_action(
            "remove", {"id": entry["id"]}, lambda _result: self.bank_refresh())))

    def show_bank_queue(self, *_):
        Gtk = self._bank_gtk
        box = self.page(f"BANK QUEUE - {self._bank_target_name()}", self.show_bank)
        available = self._bank_editable_silent()
        sc = self.touch_scrolled_window()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        for index, entry in enumerate(self.bank_queue):
            col.append(self._bank_text(f"{index + 1}. {entry['summary']}"))
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
            row.append(self._bank_button("UP", lambda *_, i=index: self.bank_move(i, -1), enabled=available and index > 0))
            row.append(self._bank_button("DOWN", lambda *_, i=index: self.bank_move(i, 1), enabled=available and index + 1 < len(self.bank_queue)))
            row.append(self._bank_button("REMOVE", lambda *_, i=index: self.bank_remove_queued(i), enabled=available))
            col.append(row)
        if not self.bank_queue:
            col.append(self._bank_text("The queue is empty. Add Pokemon from the Bank."))
        col.append(self._bank_text("Preparing offers keeps their Bank copies. Only confirmed completed trades remove them. The host stops after the queue completes."))
        sc.set_child(col)
        box.append(sc)
        if self._bank_run is not None and self._bank_run.get("error"):
            box.append(self._bank_button("RETRY BANK FINISH", self.bank_retry_finish))
        if self._bank_run is not None and self._bank_run["state"] == "prepared":
            box.append(self._bank_button("REVIEW PREPARED TRADE", self._bank_confirm_prepared))
            box.append(self._bank_button("CANCEL PREPARED TRADE", self.bank_cancel_prepared))
        box.append(self._bank_button("CLEAR QUEUE", self.bank_clear_queue, enabled=available))
        box.append(self._bank_button("PREPARE TRADE", self.bank_prepare_trade, enabled=available and bool(self.bank_queue)))
        self.win.set_child(box)

    def bank_move(self, index, delta):
        if self._bank_editable() and 0 <= index < len(self.bank_queue) and 0 <= index + delta < len(self.bank_queue):
            self.bank_queue[index], self.bank_queue[index + delta] = self.bank_queue[index + delta], self.bank_queue[index]
            self.show_bank_queue()

    def bank_remove_queued(self, index):
        if self._bank_editable() and 0 <= index < len(self.bank_queue):
            self.bank_queue.pop(index)
            self.show_bank_queue()

    def bank_clear_queue(self, *_):
        if self._bank_editable():
            self.bank_queue.clear()
            self.show_bank_queue()

    def bank_prepare_trade(self, *_):
        if not self.bank_queue or not self._bank_editable():
            return
        if self.proc is not None and self.proc.poll() is None:
            self.set_status("Stop the current host before preparing a Bank trade.")
            return
        if not self._host_prerequisites(["--keys", self._bank_config["prod_keys"]]):
            return
        token, snapshot = uuid4().hex, list(self.bank_queue)

        def ready(result):
            self._bank_run = {"token": token, "queue": snapshot, "offers": result["offers"],
                "cmd": result["cmd"], "proc": None, "state": "prepared", "completed": 0,
                "progress_pending": False, "error": ""}
            self._bank_confirm_prepared()
            self.set_status("Bank offers prepared. Confirm or cancel.")
        if self._bank_action("begin", {"token": token, "game": self.bank_game,
                "ids": [item["id"] for item in snapshot], "config": self._bank_config,
                "version": self.bank_version}, ready, timeout=180):
            self.show_bank_queue()

    def _bank_confirm_prepared(self, *_):
        run = self._bank_run
        if run is None or run["state"] != "prepared":
            return
        text = f"Trade into {self._bank_target_name()} in this order:\n"
        for index, offer in enumerate(run["offers"], 1):
            text += f"\n{index}. {offer['summary']}\n" + tracker_note(offer.get("home_tracker"))
        text += "\n\nCheck the converted Pokemon above. The original Bank records stay until their trades complete."
        box = self._bank_message("CONFIRM BANK TRADE", text, self.bank_cancel_prepared)
        box.append(self._bank_button("START TRADING", self.bank_start_prepared))
        box.append(self._bank_button("CANCEL", self.bank_cancel_prepared))

    def bank_start_prepared(self, *_):
        run = self._bank_run
        if run is None or run["state"] != "prepared":
            return
        run["state"] = "starting"
        if not self._request_radio_operation("bank-launch", lambda: self._bank_spawn(run)):
            run["state"] = "prepared"
        else:
            self.show_bank_queue()

    def _bank_spawn(self, run):
        try:
            logfile = self._bank_dir / "logs" / f"bank-{run['token']}.log"
            self._launch_ready(run["cmd"], f"Bank trade: {self._bank_target_name()}", logfile=logfile)
            if self.proc is None:
                run["start_error"] = self.current_label
                run["state"] = "prepared"
                self.bank_cancel_prepared()
                return False
            run["proc"], run["state"] = self.proc, "active"
            self._bank_rpc("attach", {"token": run["token"], "pid": self.proc.pid},
                           lambda result, error: self._bank_attached(run["token"], error))
        except Exception as exc:
            run["start_error"] = str(exc)
            run["state"] = "prepared"
            self.bank_cancel_prepared()
            self.set_status(f"Could not start Bank host: {exc}")
        return False

    def _bank_attached(self, token, error):
        run = self._bank_run
        if run is None or run["token"] != token:
            return False
        if error:
            self._bank_run_error(token, error)
        else:
            self._bank_glib.timeout_add(250, self._bank_poll_progress, token)
        return False

    def _bank_poll_progress(self, token):
        run = self._bank_run
        if run is None or run["token"] != token or run["state"] != "active":
            return False
        if not run["progress_pending"] and not run["error"] and not self._bank_finish_pending:
            run["progress_pending"] = True

            def done(result, error):
                current = self._bank_run
                if current is None or current["token"] != token:
                    return False
                current["progress_pending"] = False
                if error:
                    self._bank_run_error(token, error)
                else:
                    self._bank_apply_progress(result)
                    if result["completed"] >= len(current["queue"]) and current["proc"].poll() is None and not self.session_control.busy:
                        self.stop_current_session()
                return False
            self._bank_rpc("progress", {"token": token}, done)
        return True

    def _bank_apply_progress(self, result):
        run = self._bank_run
        if run is None or run["token"] != result["token"]:
            return
        previous = run["completed"]
        run["completed"] = max(previous, result["completed"])
        count = min(run["completed"], len(run["queue"]))
        self.bank_queue = run["queue"][count:]
        completed_ids = {entry["id"] for entry in run["queue"][:count]}
        self.bank_entries = [entry for entry in self.bank_entries if entry["id"] not in completed_ids]
        if not self.session_control.busy:
            self.set_status(f"Bank: {count}/{len(run['queue'])} confirmed trades.")
        if run["completed"] != previous:
            self._bank_refresh_controls()

    def _bank_refresh_controls(self):
        title = getattr(self, "_current_page_title", "")
        if title.startswith("BANK QUEUE"):
            self.show_bank_queue()
        elif title == "POKEMON BANK":
            self.show_bank()

    def _bank_run_error(self, token, error):
        run = self._bank_run
        if run is None or run["token"] != token:
            return
        run["error"] = error
        if run["proc"] is not None and run["proc"].poll() is None and not self.session_control.busy:
            self.stop_current_session()
        self.set_status(f"Bank needs attention: {error}. Stop the host, then use RETRY BANK FINISH in Bank.")

    def _bank_finish_if_needed(self, proc):
        run = self._bank_run
        if run is None or run["proc"] is None or run["proc"] is not proc:
            return True
        if run["error"] or self._bank_finish_pending:
            return False
        self._bank_finish_pending = True
        token = run["token"]

        def done(result, error):
            if self._bank_run is None or self._bank_run["token"] != token:
                return False
            self._bank_finish_pending = False
            if error:
                self._bank_run_error(token, error)
            else:
                self._bank_apply_progress(result)
                self._bank_run = None
                self.bank_pending = []
                self._bank_refresh_controls()
                self.set_status("Bank run finished; uncompleted Pokemon remain in the Bank.")
            return False
        self._bank_rpc("end", {"token": token, "confirm_stopped": True}, done)
        return False

    def bank_retry_finish(self, *_):
        run = self._bank_run
        if run is None:
            return
        if run["proc"] is not None and run["proc"].poll() is None:
            self.set_status("The Bank host is still stopping. Wait for it to exit.")
            return
        run["error"] = ""
        if run["proc"] is None:
            self.bank_cancel_prepared()
        else:
            self._bank_finish_if_needed(run["proc"])

    def bank_cancel_prepared(self, *_):
        run = self._bank_run
        if run is None or run["proc"] is not None or self._bank_finish_pending:
            return
        if run["state"] != "prepared":
            self.set_status("Wait for the Bank host to start, then use STOP.")
            return
        self._bank_finish_pending = True
        token = run["token"]

        def done(result, error):
            if self._bank_run is None or self._bank_run["token"] != token:
                return False
            self._bank_finish_pending = False
            if error:
                self._bank_run_error(token, error)
            else:
                self._bank_run = None
                note = f" Host did not start: {run['start_error']}" if run.get("start_error") else ""
                self.set_status("Bank trade cancelled; Bank records kept." + note)
                self.show_bank_queue()
            return False
        self._bank_rpc("end", {"token": token, "confirm_stopped": True}, done)

    def bank_confirm_recover(self, pending):
        box = self._bank_message("RECONCILE BANK RUN", "Stop the previous Bank host before continuing. This applies only confirmed trade messages in that run's log. Uncompleted Bank records stay. If startup was interrupted before a PID was recorded, confirm that no old host is running.", self.show_bank)
        box.append(self._bank_button("HOST STOPPED - RECONCILE", lambda *_: self._bank_action(
            "recover", {"token": pending["token"], "confirm_stopped": True}, lambda _result: self.bank_refresh())))
