"""Touchscreen event selection; PokeLDN builds gifts in the serialized worker."""
from __future__ import annotations

from bank_ui import tracker_note


GIFT_GAMES = {"za": "Z-A", "sv": "SCARLET / VIOLET", "bdsp": "BDSP"}


def event_facts(event):
    parts = [str(event.get("species", "Pokemon"))]
    if event.get("form"):
        parts.append(str(event["form"]))
    if event.get("level"):
        parts.append(f"level {event['level']}")
    if event.get("tera"):
        parts.append(f"Tera {event['tera']}")
    shiny = {"always": "Shiny", "random": "May be shiny"}.get(event.get("shiny"))
    if shiny:
        parts.append(shiny)
    if event.get("held_item"):
        parts.append(str(event["held_item"]))
    return " · ".join(parts)


def event_matches(event, search):
    text = " ".join(str(event.get(key, "")) for key in (
        "title", "species", "form", "card_id", "date", "ot", "ball", "held_item", "moves", "tera"))
    text += " " + event_facts(event) + " " + tracker_note(event.get("home_tracker"))
    return all(word in text.casefold() for word in search.casefold().split())


class SimulatedGiftUI:
    def _init_simulated_gifts(self):
        self._simulated_gifts_ready = False
        self._gift_game = None
        self._gift_states = {}

    def _configure_simulated_gifts(self, available):
        self._simulated_gifts_ready = available
        self._gift_states.clear()

    def _gift_state(self, game):
        if game not in GIFT_GAMES:
            raise ValueError("This game has no simulated gift menu.")
        return self._gift_states.setdefault(game, {
            "events": None, "queue": [], "search": "", "page": 0,
            "code": "00000000" if game == "za" else "", "for_receiver": True,
            "prepared": None, "steps": [], "error": "",
        })

    def _gift_back(self, game):
        return {"za": self.show_za, "sv": self.show_sv, "bdsp": self.show_bdsp}[game]

    def _gift_visible(self, game):
        return self._gift_game == game and getattr(self, "_current_page_title", "").startswith(
            ("MYSTERY GIFTS •", "GIFT DETAILS •", "GIFT QUEUE •", "READY TO SEND •"))

    def _gift_request(self, game, action, payload, callback):
        if not self._simulated_gifts_ready or not self._bank_editable():
            return False
        self._bank_busy, self._bank_cancel_allowed = True, False
        self.set_status("Reading event gifts..." if action == "gift_catalog" else "Making fresh event Pokemon...")

        def done(result, error):
            self._bank_busy = False
            if error:
                self._gift_state(game)["error"] = error
                if self._gift_visible(game):
                    self.set_status(f"Mystery Gift: {error}")
                    if action == "gift_catalog":
                        self.show_simulated_gifts(game, load=False)
                    else:
                        self.show_simulated_gift_queue(game)
            else:
                self._gift_state(game)["error"] = ""
                callback(result)
            # A different game's list may have opened while this serialized
            # request was running. Load that visible list once the worker is free.
            visible = self._gift_game
            if (visible in GIFT_GAMES and self._gift_visible(visible) and not self._bank_busy
                    and self._current_page_title.startswith("MYSTERY GIFTS •")):
                pending = self._gift_state(visible)
                if pending["events"] is None and not pending["error"]:
                    self._gift_load_catalog(visible)
            return False

        try:
            self._bank_rpc(action, payload, done, timeout=180)
        except Exception as exc:
            done(None, str(exc))
        return True

    def show_simulated_gifts(self, game, *, load=True):
        Gtk = self._bank_gtk
        self._gift_game = game
        state = self._gift_state(game)
        box = self.page(f"MYSTERY GIFTS • {GIFT_GAMES[game]}", self._gift_back(game))
        box.append(self._bank_text("Official event Pokemon delivered by local trade. Offer one Pokemon for each gift."))
        if not self._simulated_gifts_ready:
            box.append(self._bank_text("This feature needs PokeLDN's simulated gift tools. Update PokeLDN and run startup checks in Settings."))
            self.win.set_child(box)
            return
        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        search = Gtk.Entry(placeholder_text="Search Pokemon, event, moves, card number...")
        search.set_hexpand(True)
        search.set_text(state["search"])

        def searched(*_):
            state["search"], state["page"] = search.get_text(), 0
        search.connect("changed", searched)
        search.connect("activate", lambda *_: self.show_simulated_gifts(game, load=False))
        toolbar.append(search)
        toolbar.append(self._bank_button("SEARCH", lambda *_: self.show_simulated_gifts(game, load=False)))
        toolbar.append(self._bank_button(f"QUEUE ({len(state['queue'])}/6)", lambda *_: self.show_simulated_gift_queue(game)))
        box.append(toolbar)
        sc = self.touch_scrolled_window()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        events = state["events"]
        matches = [e for e in events or [] if event_matches(e, state["search"])]
        pages = max(1, (len(matches) + 7) // 8)
        state["page"] = max(0, min(state["page"], pages - 1))
        if events is None:
            col.append(self._bank_text(state["error"] or "Loading the event database..."))
        elif not matches:
            col.append(self._bank_text("No matching event Pokemon. Try another search."))
        for event in matches[state["page"] * 8:(state["page"] + 1) * 8]:
            row = self._bank_button("", lambda *_, e=event: self.show_simulated_gift_details(game, e))
            text = event_facts(event) + "\n" + event.get("title", "Event Pokemon")
            if event.get("refused") or not event.get("legal", True):
                text += " • Unavailable"
            if event.get("home_tracker"):
                text += " • HOME warning"
            label = Gtk.Label(label=text, xalign=0)
            label.set_wrap(True)
            label.set_max_width_chars(65)
            row.set_child(label)
            row.set_size_request(-1, 54)
            col.append(row)
        sc.set_child(col)
        box.append(sc)
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        footer.append(self._bank_button("PREVIOUS", lambda *_: self._gift_turn_page(game, -1), enabled=state["page"] > 0))
        footer.append(Gtk.Label(label=f"{state['page'] + 1}/{pages} · {len(matches)} gifts", hexpand=True))
        footer.append(self._bank_button("NEXT", lambda *_: self._gift_turn_page(game, 1), enabled=state["page"] + 1 < pages))
        if state["error"]:
            footer.append(self._bank_button("RETRY", lambda *_: self._gift_load_catalog(game)))
        box.append(footer)
        self.win.set_child(box)
        self._focus_button_later(footer.get_first_child())
        if events is None and load and not self._bank_busy:
            self._gift_load_catalog(game)

    def _gift_load_catalog(self, game):
        def loaded(result):
            state = self._gift_state(game)
            state["events"], state["steps"] = result["events"], result.get("steps", [])
            if self._gift_visible(game) and self._current_page_title.startswith("MYSTERY GIFTS •"):
                self.set_status("Choose an event Pokemon to inspect.")
                self.show_simulated_gifts(game, load=False)
        return self._gift_request(game, "gift_catalog", {
            "game": game, "trainer": self._bank_config["trainers"][game]}, loaded)

    def _gift_turn_page(self, game, delta):
        self._gift_state(game)["page"] += delta
        self.show_simulated_gifts(game, load=False)

    def show_simulated_gift_details(self, game, event):
        state = self._gift_state(game)
        box = self._bank_message(f"GIFT DETAILS • {GIFT_GAMES[game]}",
            "\n\n".join(filter(None, [event.get("title"), event_facts(event),
                f"Card {event.get('card_id', '')} · {event.get('date') or 'Date not listed'}",
                f"OT: {event.get('ot') or 'Receiving player, when supported'} · {event.get('ball', '')}",
                "Moves: " + ", ".join(event.get("moves", [])),
                event.get("refused") or ("PKHeX cannot make a legal copy." if not event.get("legal", True) else ""),
                tracker_note(event.get("home_tracker")),
                "You will trade a Pokemon from the Switch for this gift."])),
            lambda *_: self.show_simulated_gifts(game, load=False))
        enabled = (self._bank_editable_silent() and len(state["queue"]) < 6
                   and event.get("legal", True) and not event.get("refused"))
        box.append(self._bank_button("ADD TO GIFT QUEUE", lambda *_: self._gift_add(game, event), enabled=enabled))
        box.append(self._bank_button(f"QUEUE ({len(state['queue'])}/6)", lambda *_: self.show_simulated_gift_queue(game)))

    def _gift_add(self, game, event):
        state = self._gift_state(game)
        if not self._bank_editable() or len(state["queue"]) >= 6:
            return
        if event.get("refused") or not event.get("legal", True):
            self.set_status(event.get("refused") or "This event cannot be made legally.")
            return
        state["queue"].append(dict(event))
        state["prepared"] = None
        self.set_status(f"Added {event.get('species', 'gift')}. {len(state['queue'])}/6 queued.")
        self.show_simulated_gifts(game, load=False)

    def _gift_remove(self, game, index):
        state = self._gift_state(game)
        if self._bank_editable() and 0 <= index < len(state["queue"]):
            state["queue"].pop(index)
            state["prepared"] = None
            self.show_simulated_gift_queue(game)

    def show_simulated_gift_queue(self, game):
        Gtk = self._bank_gtk
        state = self._gift_state(game)
        box = self.page(f"GIFT QUEUE • {GIFT_GAMES[game]}", lambda *_: self.show_simulated_gifts(game, load=False))
        available = self._bank_editable_silent()
        sc = self.touch_scrolled_window()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        col.append(self._bank_text("Trade these gifts in order. Let the Switch save after the last gift, then leave trading before pressing STOP."))
        for notice in state.get("notices", []):
            col.append(self._bank_text(notice))
        for index, event in enumerate(state["queue"]):
            col.append(self._bank_text(f"{index + 1}. {event_facts(event)}\n{event.get('title', '')}"))
            col.append(self._bank_button("REMOVE", lambda *_, i=index: self._gift_remove(game, i), enabled=available))
        if not state["queue"]:
            col.append(self._bank_text("Choose event Pokemon from the gift list. Up to six per session."))
        receiver = Gtk.CheckButton(label="Made for the receiving player, when supported")
        receiver.set_active(state["for_receiver"])
        receiver.set_sensitive(available)

        def changed(control):
            state["for_receiver"], state["prepared"] = control.get_active(), None
        receiver.connect("toggled", changed)
        col.append(receiver)
        code = Gtk.Entry(placeholder_text="8 digits" if game == "za" else "Leave blank for no code")
        code.set_text(state["code"])
        code.set_max_length(8)
        code.set_sensitive(available)

        def code_changed(control):
            state["code"], state["prepared"] = control.get_text().strip(), None
        code.connect("changed", code_changed)
        col.append(self._bank_text("Room password" if game == "bdsp" else "Link code"))
        col.append(code)
        if state["error"]:
            col.append(self._bank_text(state["error"]))
        sc.set_child(col)
        box.append(sc)
        box.append(self._bank_button("PREPARE GIFTS", lambda *_: self._gift_prepare(game), enabled=available and bool(state["queue"])))
        if state["prepared"] is not None:
            box.append(self._bank_button("REVIEW PREPARED GIFTS", lambda *_: self.show_simulated_gift_review(game), enabled=available))
        self.win.set_child(box)

    def _gift_prepare(self, game):
        state = self._gift_state(game)
        if not state["queue"] or not self._bank_editable():
            return
        if not self._host_prerequisites(["--keys", self._bank_config["prod_keys"]]):
            return
        snapshot = ([event["key"] for event in state["queue"]], state["code"], state["for_receiver"])

        def prepared(result):
            current = ([event["key"] for event in state["queue"]], state["code"], state["for_receiver"])
            if current != snapshot:
                state["prepared"] = None
                if self._gift_visible(game):
                    self.set_status("Selection changed. Prepare the gifts again.")
                    self.show_simulated_gift_queue(game)
                return
            state["prepared"] = result
            if self._gift_visible(game):
                self.set_status("Gifts are ready. Review them before starting.")
                self.show_simulated_gift_review(game)
        if self._gift_request(game, "gift_prepare", {"game": game, "config": self._bank_config,
                "keys": snapshot[0], "for_receiver": snapshot[2], "code": snapshot[1]}, prepared) and self._bank_busy:
            self.show_simulated_gift_queue(game)

    def show_simulated_gift_review(self, game):
        state = self._gift_state(game)
        result = state["prepared"]
        if result is None:
            self.show_simulated_gift_queue(game)
            return
        lines = ["Trade one Pokemon from the Switch for each gift, in this order:"]
        for index, offer in enumerate(result["offers"], 1):
            lines.append(f"{index}. {offer['summary']}\n{offer.get('title', '')}")
            if result.get("for_receiver") and offer.get("your_ot") and not offer.get("handled"):
                lines.append("Trainer: the receiving player, when the console's save can be identified.")
            elif offer.get("ot"):
                lines.append(f"Trainer: {offer['ot']}")
            if offer.get("handled"):
                lines.append("This gift goes with the configured trainer because it needs a handler.")
            if tracker_note(offer.get("home_tracker")):
                lines.append(tracker_note(offer["home_tracker"]))
        lines.extend(result.get("steps", []))
        code = state["code"]
        lines.append(f"{'Room password' if game == 'bdsp' else 'Link code'}: {code or 'none'}")
        lines.append("Eligible gifts will use the receiving player's save; other gifts keep the trainers shown above."
                     if result.get("for_receiver") else "These gifts keep the trainers shown above.")
        lines.append("After the last gift, let the Switch finish saving and leave trading. Extra trades repeat the last gift. Keep TradeBox running until you have left.")
        box = self._bank_message(f"READY TO SEND • {GIFT_GAMES[game]}", "\n\n".join(lines),
                                 lambda *_: self.show_simulated_gift_queue(game))
        box.append(self._bank_button("START GIFT TRADES", lambda *_: self._gift_start(game), enabled=self._bank_editable_silent()))

    def _gift_start(self, game):
        state = self._gift_state(game)
        result = state["prepared"]
        if result is None or not self._bank_editable():
            return
        self.launch(result["cmd"], f"{GIFT_GAMES[game]} event gifts · {len(result['offers'])} queued",
                    bank_game=game, offers=result["offers"])
