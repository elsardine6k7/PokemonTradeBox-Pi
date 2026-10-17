"""Render gift pages at 800x480 on an isolated test display; no backend or radio."""
import copy
import sys
import time
from pathlib import Path


def main():
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tradebox import TradeBox
    from startup_checks import DEFAULT_CONFIG

    Gtk.init()
    app = TradeBox()
    app.register(None)
    app.win = Gtk.ApplicationWindow(application=app)
    app.win.set_decorated(False)
    app.win.set_default_size(800, 480)
    app._install_touch_scrollbar_css()
    app._backend_ready = app._bank_available = app._simulated_gifts_ready = True
    app._bank_config = copy.deepcopy(DEFAULT_CONFIG)
    app._host_prerequisites = lambda _cmd: True
    requests, launches = [], []
    app.launch = lambda cmd, label, **kwargs: launches.append((cmd, label, kwargs))

    def events(game):
        return [{"key": f"{game}-{n}", "card_id": 1000 + n,
                 "title": f"Event {n}: A special official distribution celebrating Pokemon with a very long event title",
                 "species": f"Pokemon {n}", "level": 100, "tera": "Electric",
                 "shiny": "always", "held_item": "A special held item",
                 "ball": "Cherish Ball", "ot": "Receiving player", "date": "2026-06-05",
                 "moves": ["Thunderbolt", "Protect", "Wish", "Celebrate"],
                 "legal": True, "refused": "", "home_tracker": "made" if n % 2 else "empty"}
                for n in range(123)]

    def rpc(action, payload, callback, **_kwargs):
        requests.append((action, payload))
        if action == "gift_catalog":
            result = {"events": events(payload["game"]), "steps": [
                "Start the host, join it on the Switch, and offer a Pokemon for each gift."]}
        elif action == "gift_prepare":
            chosen = {event["key"]: event for event in events(payload["game"])}
            result = {"cmd": ["test-gift-host"], "offers": [
                {"file": f"test-offer-{n}", "summary": chosen[key]["title"],
                 "title": chosen[key]["species"], "home_tracker": chosen[key]["home_tracker"],
                 "handled": n == 0}
                for n, key in enumerate(payload["keys"])], "steps": [
                    "Join the local trade on the Switch. Confirm each trade and wait through the saving messages."]}
        else:
            raise AssertionError(f"The layout smoke must not call real Bank or host operations: {action}")
        GLib.idle_add(callback, result, "")
    app._bank_rpc = rpc

    def widgets():
        found = []
        def walk(widget):
            if widget.get_visible():
                found.append(widget)
            child = widget.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()
        walk(app.win.get_child())
        return found

    def button(label):
        matches = [widget for widget in widgets()
                   if isinstance(widget, Gtk.Button) and widget.get_label() == label]
        if len(matches) != 1:
            raise AssertionError(f"Expected one {label!r} button, got {matches}")
        return matches[0]

    def click(label):
        control = button(label)
        if not control.get_sensitive():
            raise AssertionError(f"{label!r} is disabled")
        control.emit("clicked")

    def scroller():
        return next(widget for widget in widgets() if isinstance(widget, Gtk.ScrolledWindow))

    def text():
        return "\n".join(widget.get_text() for widget in widgets() if isinstance(widget, Gtk.Label))

    def fixed_actions():
        actions = []
        for control in widgets():
            if not isinstance(control, Gtk.Button):
                continue
            parent = control.get_parent()
            while parent is not None and not isinstance(parent, Gtk.ScrolledWindow):
                parent = parent.get_parent()
            if parent is None:
                actions.append(control)
        return actions

    def fully_visible(control):
        valid, bounds = control.compute_bounds(app.win)
        if (not valid or bounds.get_x() < -1 or bounds.get_y() < -1
                or bounds.get_x() + bounds.get_width() > app.win.get_width() + 1
                or bounds.get_y() + bounds.get_height() > app.win.get_height() + 1):
            raise AssertionError(f"A fixed control is outside the touchscreen: {control.get_label()!r}")

    def touch_target(control):
        allocation = control.get_allocation()
        if allocation.height < 44:
            raise AssertionError(f"A touchscreen action is too short: {control.get_label()!r}; "
                                 f"allocated={allocation.width}x{allocation.height}, mapped={control.get_mapped()}")
        fully_visible(control)

    def check(name, title, *, min_scroll=0):
        app.win.present()
        context = GLib.MainContext.default()
        deadline, stable, previous = time.monotonic() + 3, 0, None
        while time.monotonic() < deadline:
            while context.pending():
                context.iteration(False)
            root = app.win.get_child()
            scrolls = [widget.get_height() for widget in widgets() if isinstance(widget, Gtk.ScrolledWindow)]
            actions = fixed_actions()
            allocated = all(control.get_mapped() and control.get_allocation().width > 0
                            and control.get_allocation().height > 0 for control in actions)
            geometry = (app.win.get_width(), app.win.get_height(), root.get_width(), root.get_height(), tuple(scrolls),
                        tuple((control.get_label(), control.get_allocation().width,
                               control.get_allocation().height) for control in actions))
            ready = (root.get_mapped() and app._current_page_title.startswith(title)
                     and root.get_width() > 0 and root.get_height() > 0
                     and allocated
                     and (not min_scroll or bool(scrolls) and min(scrolls) >= min_scroll))
            stable = stable + 1 if ready and geometry == previous else 0
            previous = geometry
            if stable >= 3:
                break
            time.sleep(.02)
        if not root.get_mapped() or not app._current_page_title.startswith(title):
            raise AssertionError(f"{name} did not open: {app._current_page_title}")
        if not allocated or root.get_width() <= 0 or root.get_height() <= 0:
            raise AssertionError(f"{name} has unallocated actions: {geometry}")
        if app.win.get_width() > 800 or app.win.get_height() > 480:
            raise AssertionError(f"{name} forces a {app.win.get_width()}x{app.win.get_height()} window")
        if min_scroll and (not scrolls or min(scrolls) < min_scroll):
            raise AssertionError(f"{name} leaves too little room to scroll: {scrolls}")
        print(f"OK: {name}, {app.win.get_width()}x{app.win.get_height()}, scroll={scrolls}")

    try:
        app.show_home()
        check("Home with eight actions", "POKÉMON TRADE BOX")
        home_actions = ("LEGENDS Z-A", "SCARLET / VIOLET", "SWORD / SHIELD",
                        "BRILLIANT DIAMOND /\nSHINING PEARL", "FIRE RED / LEAF GREEN",
                        "POKEMON BANK", "ESP32 / FIRMWARE", "SETTINGS")
        for label in home_actions:
            touch_target(button(label))
        print("OK: all eight Home actions fit with touchscreen-sized targets")

        for game, menu, menu_title in (("za", app.show_za, "LEGENDS Z-A"),
                                       ("sv", app.show_sv, "SCARLET / VIOLET"),
                                       ("bdsp", app.show_bdsp, "BRILLIANT DIAMOND / SHINING PEARL")):
            menu()
            check(f"{game} menu", menu_title)
            touch_target(button("MYSTERY GIFT - SIMULATED"))
            if game == "sv":
                touch_target(button("LINK TRADE"))
                click("LINK TRADE")
                check("SV link trade team builder", "SCARLET / VIOLET • LINK TRADE • TEAM BUILDER", min_scroll=190)
                fully_visible(button("BUILD & HOST TEAM"))
                click("PASTE SHOWDOWN")
                check("SV link trade Showdown input", "SCARLET / VIOLET • LINK TRADE • PASTE SHOWDOWN", min_scroll=190)
                fully_visible(button("BUILD & HOST"))
                click("← BACK")
                check("SV builder returns to its game menu", menu_title)
                touch_target(button("LINK TRADE"))
            click("MYSTERY GIFT - SIMULATED")
            check(f"{game} event browser with 123 long titles", "MYSTERY GIFTS •", min_scroll=190)
            state = app._gift_state(game)
            if len(state["events"]) != 123 or requests[-1][0] != "gift_catalog":
                raise AssertionError("The event browser did not finish its catalog request")
            if requests[-1][1]["trainer"] != app._bank_config["trainers"][game]:
                raise AssertionError("The catalog used another game's trainer")
            for label in ("SEARCH", "QUEUE (0/6)", "PREVIOUS", "NEXT"):
                touch_target(button(label))
            adjustment = scroller().get_vadjustment()
            if adjustment.get_upper() <= adjustment.get_page_size():
                raise AssertionError("Long event rows should scroll independently of the footer")
            click("NEXT")
            check(f"{game} second event page", "MYSTERY GIFTS •", min_scroll=190)
            if state["page"] != 1:
                raise AssertionError("The event page did not advance")
            search = next(widget for widget in widgets() if isinstance(widget, Gtk.Entry))
            search.set_text("Event 117:")
            click("SEARCH")
            check(f"{game} event search", "MYSTERY GIFTS •", min_scroll=190)
            if state["page"] != 0 or "1 gifts" not in text():
                raise AssertionError("Search did not reset the page and find the requested event")
            search = next(widget for widget in widgets() if isinstance(widget, Gtk.Entry))
            search.set_text("")
            search.emit("activate")
            check(f"{game} cleared event search", "MYSTERY GIFTS •", min_scroll=190)

            refusal = "This event never reached a save in the configured trainer's language."
            refused = dict(state["events"][0], legal=False, refused=refusal)
            app.show_simulated_gift_details(game, refused)
            check(f"{game} refused gift details", "GIFT DETAILS •", min_scroll=190)
            if button("ADD TO GIFT QUEUE").get_sensitive() or refusal not in text():
                raise AssertionError("A refused gift must explain why and disable Add")
            fully_visible(button("ADD TO GIFT QUEUE"))
            click("← BACK")
            check(f"{game} details return to browser", "MYSTERY GIFTS •", min_scroll=190)
            for event in state["events"][:6]:
                app._gift_add(game, event)
            click("QUEUE (6/6)")
            check(f"{game} six-gift queue", "GIFT QUEUE •", min_scroll=190)
            touch_target(button("PREPARE GIFTS"))
            if len(state["queue"]) != 6 or "Let the Switch save" not in text():
                raise AssertionError("The queue lost gifts or its save instruction")
            click("PREPARE GIFTS")
            check(f"{game} prepared review and HOME warnings", "READY TO SEND •", min_scroll=190)
            touch_target(button("START GIFT TRADES"))
            if "HOME tracker warning:" not in text() or "let the Switch finish saving" not in text():
                raise AssertionError("The review lost its HOME warning or save-and-exit instruction")
            payload = requests[-1][1]
            if payload["keys"] != [event["key"] for event in state["queue"]]:
                raise AssertionError("Preparation changed the selected gift order")
            click("START GIFT TRADES")
            if launches[-1][2]["bank_game"] != game or len(launches[-1][2]["offers"]) != 6:
                raise AssertionError("Start did not pass the reviewed game and six offers to the host owner")
        print("OK: all gift screens use stub requests and launch callbacks; no backend or radio opened")
    finally:
        app.win.destroy()
        app.quit()


if __name__ == "__main__":
    main()
