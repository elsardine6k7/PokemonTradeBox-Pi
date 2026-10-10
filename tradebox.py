#!/usr/bin/env python3
from __future__ import annotations

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib, Pango

import copy
import json
import os
import signal
import subprocess
import re
import sys
import tempfile
import time
from pathlib import Path

HOME = Path.home()
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(
    os.environ.get("POKEMON_TRADEBOX_CONFIG", str(APP_DIR / "config.json"))
).expanduser()

DEFAULT_CONFIG = {
    "pokeldn_repo": "~/pokeldn",
    "prod_keys": "~/.switch/prod.keys",
    "radio": "auto",
    "frlg_version": "firered",
    "trainers": {
        "za": {"ot": "PLAYER", "tid": 0, "sid": 0, "language": 2, "gender": 0},
        "swsh": {"ot": "PLAYER", "tid": 0, "sid": 0, "language": 2, "gender": 0},
        "frlg": {"ot": "PLAYER", "tid": 0, "sid": 0, "language": 2, "gender": 0},
    },
}


def load_config():
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            user = json.load(fh)

        for key in ("pokeldn_repo", "prod_keys", "radio", "frlg_version"):
            if key in user:
                cfg[key] = user[key]

        trainers = user.get("trainers") or {}
        for game in cfg["trainers"]:
            if isinstance(trainers.get(game), dict):
                cfg["trainers"][game].update(trainers[game])
    return cfg


CONFIG = load_config()
REPO = Path(str(CONFIG["pokeldn_repo"])).expanduser()
PYTHON = REPO / ".venv" / "bin" / "python"
KEYS = Path(str(CONFIG["prod_keys"])).expanduser()
RADIO = str(CONFIG.get("radio") or "auto")
FRLG_VERSION = str(CONFIG.get("frlg_version") or "firered").lower()

LOG_DIR = APP_DIR / "logs"
GIFT_DIR = APP_DIR / "gifts"
LOG_DIR.mkdir(parents=True, exist_ok=True)
GIFT_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(REPO))
from pokeldn import gifts, pokemon
from pokeldn.swsh import gift_builder as swgift
from pokeldn.frlg.gift import builder as frgift
from pokeldn.swsh import gift_file, wc8
from pokeldn.swsh import events as swevents

TRAINERS = CONFIG["trainers"]


STATS = ("hp", "atk", "def", "spa", "spd", "spe")

NATURE_NAMES = [
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
]

STAT_SHOWDOWN = {
    "hp": "HP",
    "atk": "Atk",
    "def": "Def",
    "spa": "SpA",
    "spd": "SpD",
    "spe": "Spe",
}

FRIENDSHIP_LABELS = [
    "Default",
    "0",
    "70",
    "160",
    "220",
    "255 (MAX)",
]

FRIENDSHIP_VALUES = [
    "",
    "0",
    "70",
    "160",
    "220",
    "255",
]


def text_of(view: Gtk.TextView) -> str:
    buf = view.get_buffer()
    return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True).strip()


def entry_int(entry: Gtk.Entry, default=0) -> int:
    raw = entry.get_text().strip()
    return int(raw) if raw else default


class TradeBox(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="com.rick.pokemontradebox")
        self.win = None
        self.proc: subprocess.Popen | None = None
        self.proc_log = None
        self.current_label = "Idle"
        self.name_cache = {}
        self.touch_window = None

    def do_activate(self):
        self.win = Gtk.ApplicationWindow(application=self)
        self.win.set_title("Pokemon Trade Box")
        self.win.set_decorated(False)
        self.win.maximize()
        self.show_home()
        self.win.present()

    # ---------- common UI ----------

    def page(self, title: str, back_cb=None):
        # Compact layout for an 800x480 touchscreen.
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        outer.set_margin_top(4)
        outer.set_margin_bottom(4)
        outer.set_margin_start(5)
        outer.set_margin_end(5)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)

        if back_cb:
            b = Gtk.Button(label="← BACK")
            b.connect("clicked", back_cb)
            head.append(b)

        lbl = Gtk.Label()
        lbl.set_markup(f'<span size="13500" weight="bold">{title}</span>')
        lbl.set_hexpand(True)
        lbl.set_xalign(0.5)
        lbl.set_ellipsize(Pango.EllipsizeMode.END)
        lbl.set_tooltip_text(title)
        head.append(lbl)

        stop = Gtk.Button(label="STOP")
        stop.add_css_class("destructive-action")
        stop.connect("clicked", self.stop_current_session)
        head.append(stop)

        outer.append(head)

        self.status = Gtk.Label(label=self.current_label)
        self.status.set_wrap(True)
        outer.append(self.status)
        return outer

    def button(self, label, callback, *, css=None):
        b = Gtk.Button(label=label)
        b.set_hexpand(True)
        b.set_vexpand(True)
        if css:
            b.add_css_class(css)
        b.connect("clicked", callback)
        return b

    def set_status(self, text):
        self.current_label = text
        if hasattr(self, "status") and self.status:
            self.status.set_text(text)

    def show_home(self, *_):
        box = self.page("POKÉMON TRADE BOX")
        box.append(self.button("LEGENDS Z-A", self.show_za))
        box.append(self.button("SWORD / SHIELD", self.show_swsh))
        box.append(self.button("FIRE RED / LEAF GREEN", self.show_frlg))
        box.append(self.button("SETTINGS", self.show_settings))
        self.win.set_child(box)

    # ---------- process/radio control ----------

    def _radio_env(self):
        return RADIO if RADIO.startswith("esp32:") else f"esp32:{RADIO}"

    def _serial_radio_device(self):
        raw = RADIO[6:] if RADIO.startswith("esp32:") else RADIO

        if raw and raw != "auto":
            path = Path(raw).expanduser()
            return path if path.exists() else None

        by_id = Path("/dev/serial/by-id")
        if by_id.exists():
            candidates = sorted(by_id.glob("*"))
            preferred = [
                p for p in candidates
                if any(token in p.name.casefold()
                       for token in ("cp210", "silicon_labs", "usb_to_uart"))
            ]
            if preferred:
                return preferred[0]
            if candidates:
                return candidates[0]

        fallback = Path("/dev/ttyUSB0")
        return fallback if fallback.exists() else None

    def reset_esp32(self):
        import serial

        port = self._serial_radio_device()
        if port is None:
            return

        dev = serial.Serial()
        dev.port = str(port)
        dev.baudrate = 115200
        dev.timeout = 0.5
        dev.dtr = False
        dev.rts = False
        dev.open()
        try:
            time.sleep(0.05)
            dev.rts = True
            time.sleep(0.15)
            dev.rts = False
            time.sleep(0.8)
        finally:
            dev.close()

    def _cleanup_proc(self):
        if self.proc and self.proc.poll() is not None:
            self.proc = None
        if self.proc_log:
            try:
                self.proc_log.close()
            except Exception:
                pass
            self.proc_log = None

    def stop_current_session(self, *_):
        if self.proc and self.proc.poll() is None:
            try:
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
                self.proc.wait(timeout=3)
            except Exception:
                try:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                except Exception:
                    pass

        # Also catches a manually-started or orphaned session.
        for pattern in (
            str(REPO / "bin/za_host.py"),
            str(REPO / "bin/za_join.py"),
            str(REPO / "bin/swsh_host.py"),
            str(REPO / "bin/swsh_connect.py"),
            str(REPO / "bin/swsh_gift_host.py"),
            str(REPO / "bin/frlg_trade_host.py"),
            str(REPO / "bin/frlg_trade_join.py"),
            str(REPO / "bin/frlg_mg_host.py"),
        ):
            subprocess.run(["pkill", "-TERM", "-f", pattern],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        time.sleep(0.5)
        self._cleanup_proc()
        try:
            self.reset_esp32()
            self.set_status("Stopped. ESP32 ready.")
        except Exception as exc:
            self.set_status(f"Stopped. ESP32 reset warning: {exc}")

    def launch(self, cmd, label, *, reset=True):
        self.stop_current_session()
        if reset:
            try:
                self.reset_esp32()
            except Exception as exc:
                self.set_status(f"ESP32 reset failed: {exc}")
                return

        stamp = time.strftime("%Y%m%d-%H%M%S")
        logfile = LOG_DIR / f"{stamp}.log"
        self.proc_log = open(logfile, "w", encoding="utf-8")
        env = os.environ.copy()
        env["POKELDN_RADIO"] = self._radio_env()
        self.proc = subprocess.Popen(
            [str(x) for x in cmd],
            cwd=str(REPO),
            env=env,
            stdout=self.proc_log,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )
        self.set_status(f"{label}  •  PID {self.proc.pid}")
        GLib.timeout_add_seconds(1, self.poll_process)

    def poll_process(self):
        if not self.proc:
            return False
        rc = self.proc.poll()
        if rc is None:
            return True
        self.set_status("Session finished." if rc == 0 else f"Session ended with error {rc}. Check logs.")
        self._cleanup_proc()
        return False

    # ---------- Showdown builders ----------

    def showdown_files(self, game: str, text: str):
        trainer = TRAINERS[game]
        try:
            sets = pokemon.SERVICE.paste(game, text, trainer)
        except pokemon.BuilderError as exc:
            raise ValueError(str(exc))

        if not sets:
            raise ValueError("No Pokémon set found.")

        # The stock pokeldn Showdown parser reads Happiness/Friendship but
        # does not pass it into the PKHeX builder. Preserve explicit values
        # per set so the patched builder can apply them.
        friendship_by_set = []
        for block in re.split(r"\n\s*\n", text.strip()):
            block = block.strip()
            if not block or block.startswith("==="):
                continue
            match = re.search(
                r"(?im)^\s*(?:Happiness|Friendship)\s*:\s*(\d{1,3})\s*$",
                block,
            )
            friendship_by_set.append(int(match.group(1)) if match else None)

        output = []
        for n, s in enumerate(sets, 1):
            errors = s.get("errors") or []
            if errors:
                raise ValueError(f"Set {n}: " + "; ".join(errors))

            options = dict(s.get("options") or {})

            if n - 1 < len(friendship_by_set):
                friendship = friendship_by_set[n - 1]
                if friendship is not None:
                    if friendship < 0 or friendship > 255:
                        raise ValueError(f"Set {n}: friendship must be 0–255.")
                    options["friendship"] = friendship

            # Your preference: omitted IVs means 31 in all six stats.
            if "IVs:" not in text:
                options["ivs"] = {k: 31 for k in STATS}

            try:
                info = pokemon.SERVICE.make(
                    game,
                    int(s["species_id"]),
                    trainer,
                    level=int(s.get("level") or 0),
                    shiny=bool(s.get("shiny")),
                    nickname=str(s.get("nickname") or ""),
                    options=options,
                )
            except pokemon.BuilderError as exc:
                raise ValueError(f"Set {n}: {exc}")
            output.append(info)
        return output

    def showdown_editor(self, title, game, start_cb, back_cb):
        # Touch builder is now the default. The old paste editor is still
        # available from a button so nothing is lost.
        self.show_touch_team_builder(title, game, start_cb, back_cb)

    def show_showdown_text_editor(self, title, game, start_cb, back_cb):
        outer = self.page(title + " • PASTE SHOWDOWN", back_cb)

        view = Gtk.TextView()
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_monospace(True)
        view.set_vexpand(True)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        try:
            scroll.set_kinetic_scrolling(True)
            scroll.set_overlay_scrolling(True)
        except Exception:
            pass
        scroll.set_child(view)
        outer.append(scroll)

        hint = Gtk.Label(
            label="Paste one or more Pokémon Showdown sets. Omitted IVs = 31 in all six stats."
        )
        hint.set_wrap(True)
        outer.append(hint)

        go = Gtk.Button(label="BUILD & HOST")
        go.add_css_class("suggested-action")
        go.connect("clicked", start_cb, view)
        outer.append(go)
        self.win.set_child(outer)

    def _blank_team_slot(self):
        return {
            "species": "",
            "level": "50",
            "item": "",
            "nature": 0,  # 0 = Random / omitted
            "friendship": "",  # blank = builder/game default
            "shiny": False,
            "moves": ["", "", "", ""],
            "evs": {k: 0 for k in STATS},
        }

    def _team_slot_summary(self, slot, number):
        species = slot.get("species", "").strip()
        if not species:
            return f"{number}. + ADD POKÉMON"

        level = slot.get("level", "50") or "50"
        item = slot.get("item", "").strip()

        line = f"{number}. {species}  •  Lv {level}"
        if item:
            line += f"  •  {item}"

        friendship = str(slot.get("friendship", "")).strip()
        if friendship:
            line += f"  •  Friendship {friendship}"

        return line

    def _team_to_showdown(self, team):
        sets = []

        for slot in team[:6]:
            species = str(slot.get("species", "")).strip()
            if not species:
                continue

            item = str(slot.get("item", "")).strip()
            header = species + (f" @ {item}" if item else "")
            lines = [header]

            level = str(slot.get("level", "50")).strip() or "50"
            lines.append(f"Level: {level}")

            if slot.get("shiny"):
                lines.append("Shiny: Yes")

            friendship = str(slot.get("friendship", "")).strip()
            if friendship:
                lines.append(f"Happiness: {friendship}")

            evs = slot.get("evs") or {}
            ev_parts = []
            for stat in STATS:
                amount = int(evs.get(stat, 0) or 0)
                if amount:
                    ev_parts.append(f"{amount} {STAT_SHOWDOWN[stat]}")
            if ev_parts:
                lines.append("EVs: " + " / ".join(ev_parts))

            nature_index = int(slot.get("nature", 0) or 0)
            if 1 <= nature_index <= len(NATURE_NAMES):
                lines.append(f"{NATURE_NAMES[nature_index - 1]} Nature")

            for move in slot.get("moves", [])[:4]:
                move = str(move).strip()
                if move:
                    lines.append(f"- {move}")

            sets.append("\n".join(lines))

        return "\n\n".join(sets)

    def show_touch_team_builder(self, title, game, start_cb, back_cb, team=None):
        if team is None:
            team = [self._blank_team_slot() for _ in range(6)]

        outer = self.page(title + " • TEAM BUILDER", back_cb)

        hint = Gtk.Label(
            label="Build up to 6 Pokémon. Tap a slot to edit it. "
                  "IVs default to 31 in all six stats."
        )
        hint.set_wrap(True)
        outer.append(hint)

        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        try:
            sc.set_kinetic_scrolling(True)
            sc.set_overlay_scrolling(True)
        except Exception:
            pass

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        col.set_margin_end(2)

        for i, slot in enumerate(team):
            b = Gtk.Button(label=self._team_slot_summary(slot, i + 1))
            b.set_hexpand(True)
            b.connect(
                "clicked",
                lambda _b, idx=i: self.show_team_slot_editor(
                    title, game, start_cb, back_cb, team, idx
                ),
            )
            col.append(b)

        sc.set_child(col)
        outer.append(sc)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        paste = Gtk.Button(label="PASTE SHOWDOWN")
        paste.set_hexpand(True)
        paste.connect(
            "clicked",
            lambda *_: self.show_showdown_text_editor(
                title, game, start_cb, back_cb
            ),
        )
        actions.append(paste)

        clear = Gtk.Button(label="CLEAR TEAM")
        clear.set_hexpand(True)

        def clear_team(*_):
            for idx in range(6):
                team[idx] = self._blank_team_slot()
            self.show_touch_team_builder(title, game, start_cb, back_cb, team)

        clear.connect("clicked", clear_team)
        actions.append(clear)
        outer.append(actions)

        go = Gtk.Button(label="BUILD & HOST TEAM")
        go.add_css_class("suggested-action")

        def build_and_host(*_):
            chosen = [s for s in team if str(s.get("species", "")).strip()]
            if not chosen:
                self.set_status("Add at least one Pokémon first.")
                return

            for n, slot in enumerate(chosen, 1):
                total = sum(int((slot.get("evs") or {}).get(k, 0) or 0) for k in STATS)
                if total > 510:
                    self.set_status(f"Pokémon {n}: EV total is {total}; maximum is 510.")
                    return

            showdown = self._team_to_showdown(team)

            # Reuse every existing, already-tested host path by handing it a
            # temporary TextView containing the generated Showdown text.
            temp_view = Gtk.TextView()
            temp_view.get_buffer().set_text(showdown)
            start_cb(None, temp_view)

        go.connect("clicked", build_and_host)
        outer.append(go)

        self.win.set_child(outer)

    def show_team_slot_editor(self, title, game, start_cb, back_cb, team, index):
        slot = team[index]

        outer, col = self.build_scroll_page(
            f"{title} • POKÉMON {index + 1}",
            lambda *_: self.show_touch_team_builder(
                title, game, start_cb, back_cb, team
            ),
        )

        species = self.autocomplete_field(
            "species",
            "Tap to choose species",
            slot.get("species", ""),
            game=game,
        )
        level = self.numeric_field(
            "Level",
            slot.get("level", "50"),
            1,
            100,
            1,
        )
        item = self.autocomplete_field(
            "items",
            "No held item",
            slot.get("item", ""),
            game=game,
        )

        nature = Gtk.DropDown.new_from_strings(["Random"] + NATURE_NAMES)
        nature.set_selected(int(slot.get("nature", 0) or 0))

        friendship = Gtk.DropDown.new_from_strings(FRIENDSHIP_LABELS)
        current_friendship = str(slot.get("friendship", "")).strip()
        try:
            friendship.set_selected(FRIENDSHIP_VALUES.index(current_friendship))
        except ValueError:
            friendship.set_selected(0)

        shiny = Gtk.CheckButton(label="Shiny")
        shiny.set_active(bool(slot.get("shiny")))

        col.append(self.labeled("Species", species))
        col.append(self.labeled("Level", level))
        col.append(self.labeled("Held item", item))
        col.append(self.labeled("Nature", nature))
        col.append(self.labeled("Friendship", friendship))
        col.append(shiny)

        moves = []
        for n in range(4):
            field = self.autocomplete_field(
                "moves",
                f"Move {n + 1}",
                (slot.get("moves") or ["", "", "", ""])[n],
                game=game,
            )
            col.append(self.labeled(f"Move {n + 1}", field))
            moves.append(field)

        evs = slot.get("evs") or {k: 0 for k in STATS}
        ev_total = sum(int(evs.get(k, 0) or 0) for k in STATS)
        ev_text = ", ".join(
            f"{STAT_SHOWDOWN[k]} {int(evs.get(k, 0) or 0)}"
            for k in STATS
            if int(evs.get(k, 0) or 0)
        ) or "None"

        ev_label = Gtk.Label(
            label=f"EVs: {ev_text} • Total {ev_total}/510",
            xalign=0,
        )
        ev_label.set_wrap(True)
        col.append(ev_label)

        edit_evs = Gtk.Button(label="EDIT EVs")
        edit_evs.connect(
            "clicked",
            lambda *_: self._save_team_slot_and_open_evs(
                title,
                game,
                start_cb,
                back_cb,
                team,
                index,
                species,
                level,
                item,
                nature,
                friendship,
                shiny,
                moves,
            ),
        )
        col.append(edit_evs)

        clear = Gtk.Button(label="CLEAR THIS SLOT")
        clear.add_css_class("destructive-action")

        def clear_slot(*_):
            team[index] = self._blank_team_slot()
            self.show_touch_team_builder(title, game, start_cb, back_cb, team)

        clear.connect("clicked", clear_slot)
        col.append(clear)

        save = Gtk.Button(label="SAVE POKÉMON")
        save.add_css_class("suggested-action")

        def save_slot(*_):
            species_name = species.get_text().strip()
            if not species_name:
                self.set_status("Choose a species, or use CLEAR THIS SLOT.")
                return

            team[index]["species"] = species_name
            team[index]["level"] = level.get_text().strip() or "50"
            team[index]["item"] = item.get_text().strip()
            team[index]["nature"] = int(nature.get_selected())
            friendship_index = int(friendship.get_selected())
            team[index]["friendship"] = FRIENDSHIP_VALUES[friendship_index]
            team[index]["shiny"] = shiny.get_active()
            team[index]["moves"] = [m.get_text().strip() for m in moves]

            self.show_touch_team_builder(title, game, start_cb, back_cb, team)

        save.connect("clicked", save_slot)
        col.append(save)

    def _save_team_slot_and_open_evs(
        self,
        title,
        game,
        start_cb,
        back_cb,
        team,
        index,
        species,
        level,
        item,
        nature,
        friendship,
        shiny,
        moves,
    ):
        # Save the visible fields first so backing out of the EV page doesn't
        # throw away what the user already selected.
        team[index]["species"] = species.get_text().strip()
        team[index]["level"] = level.get_text().strip() or "50"
        team[index]["item"] = item.get_text().strip()
        team[index]["nature"] = int(nature.get_selected())
        friendship_index = int(friendship.get_selected())
        team[index]["friendship"] = FRIENDSHIP_VALUES[friendship_index]
        team[index]["shiny"] = shiny.get_active()
        team[index]["moves"] = [m.get_text().strip() for m in moves]

        self.show_team_ev_editor(
            title, game, start_cb, back_cb, team, index
        )

    def show_team_ev_editor(self, title, game, start_cb, back_cb, team, index):
        outer, col = self.build_scroll_page(
            f"{title} • POKÉMON {index + 1} • EVs",
            lambda *_: self.show_team_slot_editor(
                title, game, start_cb, back_cb, team, index
            ),
        )

        hint = Gtk.Label(
            label="0–252 per stat, maximum 510 total. "
                  "Use − / + or tap the middle value for an exact number."
        )
        hint.set_wrap(True)
        col.append(hint)

        current = team[index].get("evs") or {k: 0 for k in STATS}
        controls = {}

        for stat in STATS:
            control = self.numeric_field(
                STAT_SHOWDOWN[stat],
                str(int(current.get(stat, 0) or 0)),
                0,
                252,
                4,
            )
            col.append(self.labeled(STAT_SHOWDOWN[stat], control))
            controls[stat] = control

        reset = Gtk.Button(label="RESET ALL EVs TO 0")

        def reset_all(*_):
            for control in controls.values():
                control.set_text("0")

        reset.connect("clicked", reset_all)
        col.append(reset)

        save = Gtk.Button(label="SAVE EVs")
        save.add_css_class("suggested-action")

        def save_evs(*_):
            values = {}
            for stat, control in controls.items():
                raw = control.get_text().strip() or "0"
                values[stat] = max(0, min(252, int(raw)))

            total = sum(values.values())
            if total > 510:
                self.set_status(f"EV total is {total}; maximum is 510.")
                return

            team[index]["evs"] = values
            self.show_team_slot_editor(
                title, game, start_cb, back_cb, team, index
            )

        save.connect("clicked", save_evs)
        col.append(save)

    # ---------- Z-A ----------

    def show_za(self, *_):
        self.showdown_editor("LEGENDS Z-A", "za", self.host_za, self.show_home)

    def host_za(self, button, view):
        text = text_of(view)
        if not text:
            self.set_status("Add or paste at least one Z-A Pokémon first.")
            return

        try:
            infos = self.showdown_files("za", text)
        except ValueError as exc:
            self.set_status(f"Build failed: {exc}")
            return

        cmd = [
            PYTHON, "-u", REPO / "bin/za_host.py",
            "--keys", KEYS,
            "--trainer-name", str(TRAINERS["za"]["ot"]),
            "--offer-out", APP_DIR / "received-za.pa9",
            "--seconds", "900",
        ]

        for info in infos[:6]:
            cmd += ["--trade-offer", info["file"]]

        self.launch(cmd, f"Z-A hosting {min(len(infos), 6)} offer(s)")

    # ---------- Sword/Shield menu ----------

    def show_swsh(self, *_):
        box = self.page("SWORD / SHIELD", self.show_home)
        box.append(self.button("LINK TRADE", self.show_swsh_trade))
        box.append(self.button("MYSTERY GIFT", self.show_swsh_gift))
        box.append(self.button("RECEIVED POKÉMON", self.show_swsh_received))
        self.win.set_child(box)

    def show_swsh_trade(self, *_):
        self.showdown_editor("SWORD / SHIELD • LINK TRADE", "swsh",
                             self.host_swsh_trade, self.show_swsh)

    def host_swsh_trade(self, button, view):
        text = text_of(view)
        if not text:
            self.set_status("Paste a Showdown set first.")
            return
        try:
            infos = self.showdown_files("swsh", text)
        except ValueError as exc:
            self.set_status(f"Build failed: {exc}")
            return

        cmd = [
            PYTHON, "-u", REPO / "bin/swsh_host.py",
            "--keys", KEYS,
            "--trainer-name", str(TRAINERS["swsh"]["ot"]),
            "--trainer-tid", str(TRAINERS["swsh"]["tid"]),
            "--trainer-sid", str(TRAINERS["swsh"]["sid"]),
            "--received", REPO / "received-sword.pk8",
            "--seconds", "900",
        ]
        # Intentionally NO --code. Uncoded hosting is what worked on your Sword.
        for info in infos:
            cmd += ["--offer-file", info["file"]]

        self.launch(cmd, f"Sword/Shield hosting {len(infos)} offer(s)")

    def show_swsh_received(self, *_):
        box = self.page("SWORD / SHIELD • RECEIVED", self.show_swsh)
        paths = sorted(REPO.glob("received-sword*.pk8"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not paths:
            box.append(Gtk.Label(label="No received Sword/Shield Pokémon saved yet."))
        else:
            sc = Gtk.ScrolledWindow()
            sc.set_vexpand(True)
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            for p in paths[:50]:
                col.append(Gtk.Label(label=p.name, xalign=0))
            sc.set_child(col)
            box.append(sc)
        self.win.set_child(box)

    # ---------- Sword/Shield Mystery Gift ----------

    def show_swsh_gift(self, *_):
        box = self.page("SWORD / SHIELD • MYSTERY GIFT", self.show_swsh)
        box.append(self.button("USE A PRESET", self.show_gift_presets))
        box.append(self.button("OFFICIAL EVENTS", self.show_gift_events))
        box.append(self.button("BUILD YOUR OWN", self.show_gift_build_menu))
        box.append(self.button("OPEN A FILE", self.open_gift_file))
        self.win.set_child(box)

    def save_and_host_gift(self, gift, label):
        path = GIFT_DIR / "current-swsh.pokegift"
        gifts.save(str(path), gift)
        self.launch(
            [PYTHON, "-u", REPO / "bin/swsh_gift_host.py",
             "--keys", KEYS,
             "--gift-file", path,
             "--seconds", "900"],
            f"Mystery Gift: {label}",
        )

    def show_gift_presets(self, *_):
        box = self.page("MYSTERY GIFT • PRESETS", self.show_swsh_gift)
        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for preset in swgift.PRESETS:
            b = Gtk.Button(label=f"{preset.label}\n{preset.summary}")
            b.connect("clicked", self.send_preset, preset.key)
            col.append(b)
        sc.set_child(col)
        box.append(sc)
        self.win.set_child(box)

    def send_preset(self, button, key):
        preset = swgift.PRESET[key]
        try:
            gift = swgift.compile(copy.deepcopy(preset.state))
            self.save_and_host_gift(gift, preset.label)
        except Exception as exc:
            self.set_status(f"Could not build preset: {exc}")

    def show_gift_events(self, *_):
        box = self.page("MYSTERY GIFT • OFFICIAL EVENTS", self.show_swsh_gift)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search Pikachu, shiny, Master Ball...")
        box.append(search)

        count = Gtk.Label(xalign=0)
        box.append(count)

        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        sc.set_child(col)
        box.append(sc)

        cards = swevents.load()

        def render(*_):
            child = col.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                col.remove(child)
                child = nxt

            words = search.get_text().casefold().split()
            shown = [
                c for c in cards
                if all(w in f"{c['label']} {c['group']} {c['summary']}".casefold() for w in words)            ]
            count.set_text(f"{len(shown)} of {len(cards)} cards")
            for card in shown:
                b = Gtk.Button(label=f"{card['label']}\n{card['group']} • {card['summary']}")
                b.connect("clicked", self.send_event, card["key"])
                col.append(b)

        search.connect("search-changed", render)
        render()
        self.win.set_child(box)

    def send_event(self, button, key):
        try:
            gift = swevents.gift(key)
            label = swevents.by_key()[key]["label"]
            self.save_and_host_gift(gift, label)
        except Exception as exc:
            self.set_status(f"Could not build event: {exc}")

    def show_gift_build_menu(self, *_):
        box = self.page("MYSTERY GIFT • BUILD YOUR OWN", self.show_swsh_gift)
        for key, label, _icon in swgift.KINDS:
            box.append(self.button(label.upper(), lambda b, k=key: self.show_gift_builder(k)))
        self.win.set_child(box)

    # ---------- touch-friendly input helpers ----------

    def _name_rows(self, kind, game="swsh"):
        """Return cached (id, name) rows for a game-specific touch selector."""
        cache_key = (game, kind)
        if cache_key not in self.name_cache:
            try:
                self.name_cache[cache_key] = pokemon.SERVICE.names(game, kind)
            except Exception:
                self.name_cache[cache_key] = []

        rows = [
            (int(x["id"]), str(x["name"]))
            for x in self.name_cache[cache_key]
        ]
        rows.sort(key=lambda x: x[1].casefold())
        return rows

    def _focus_button_later(self, button):
        # Keeping focus on a button prevents Squeekboard from appearing just
        # because a selector window opened.
        def do_focus():
            try:
                button.grab_focus()
            except Exception:
                pass
            return False

        GLib.idle_add(do_focus)

    def open_name_picker(self, kind, target, title, game="swsh"):
        """
        Full-screen touch picker.

        Nothing editable is focused when this opens, so the keyboard stays
        closed while the user swipes. The keyboard appears only after SEARCH
        is deliberately tapped. BROWSE RESULTS moves focus back to a button
        and lets Squeekboard close before scrolling.
        """
        picker = Gtk.ApplicationWindow(application=self)
        picker.set_title(title)
        picker.set_transient_for(self.win)
        picker.set_modal(True)
        picker.set_decorated(False)
        picker.maximize()
        self.touch_window = picker

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(10)
        root.set_margin_end(10)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        close = Gtk.Button(label="← BACK")
        close.connect("clicked", lambda *_: picker.close())
        head.append(close)

        heading = Gtk.Label()
        heading.set_markup(f'<span size="17000" weight="bold">{title}</span>')
        heading.set_hexpand(True)
        head.append(heading)

        clear = Gtk.Button(label="CLEAR")
        head.append(clear)
        root.append(head)

        current = Gtk.Label(
            label=f"Selected: {target.get_text() or 'None'}",
            xalign=0,
        )
        current.set_wrap(True)
        root.append(current)

        search_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=7)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Tap here only when you want to type a search")
        search.set_hexpand(True)
        search_row.append(search)

        browse = Gtk.Button(label="BROWSE RESULTS")
        search_row.append(browse)
        root.append(search_row)

        count = Gtk.Label(xalign=0)
        root.append(count)

        store = Gtk.StringList()
        selection = Gtk.SingleSelection.new(store)

        factory = Gtk.SignalListItemFactory()

        def setup_row(_factory, item):
            label = Gtk.Label(xalign=0)
            label.set_margin_top(11)
            label.set_margin_bottom(11)
            label.set_margin_start(12)
            label.set_margin_end(12)
            label.set_wrap(True)
            item.set_child(label)

        def bind_row(_factory, item):
            obj = item.get_item()
            label = item.get_child()
            label.set_text(obj.get_string() if obj else "")

        factory.connect("setup", setup_row)
        factory.connect("bind", bind_row)

        listview = Gtk.ListView.new(selection, factory)
        try:
            listview.set_single_click_activate(True)
        except Exception:
            pass

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_hexpand(True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        try:
            scroll.set_kinetic_scrolling(True)
            scroll.set_overlay_scrolling(True)
        except Exception:
            pass
        scroll.set_child(listview)
        root.append(scroll)

        all_rows = self._name_rows(kind, game)
        shown_rows = []

        def replace_store(rows):
            shown_rows[:] = rows

            # Gtk.StringList is intentionally rebuilt in place so the
            # selection/list view remain stable.
            while store.get_n_items():
                store.remove(store.get_n_items() - 1)

            for _ident, name in rows:
                store.append(name)

            count.set_text(
                f"{len(rows)} result{'s' if len(rows) != 1 else ''}"
                + (f" • {len(all_rows)} total" if len(rows) != len(all_rows) else "")
            )

        def do_filter(*_):
            q = search.get_text().strip().casefold()

            if not q:
                replace_store(all_rows)
                return

            starts = []
            contains = []

            for ident, name in all_rows:
                folded = name.casefold()
                ident_text = str(ident)

                if q.isdigit():
                    if ident_text == q:
                        starts.append((ident, name))
                    elif ident_text.startswith(q):
                        contains.append((ident, name))
                elif folded.startswith(q):
                    starts.append((ident, name))
                elif q in folded:
                    contains.append((ident, name))

            replace_store(starts + contains)

        def activate(_listview, position):
            pos = int(position)
            if 0 <= pos < len(shown_rows):
                _ident, name = shown_rows[pos]
                target.set_text(name)
                picker.close()

        def clear_value(*_):
            target.set_text("")
            picker.close()

        def browse_results(*_):
            # Moving focus away from SearchEntry asks Squeekboard to close.
            browse.grab_focus()

        clear.connect("clicked", clear_value)
        browse.connect("clicked", browse_results)
        search.connect("search-changed", do_filter)
        listview.connect("activate", activate)

        do_filter()
        picker.set_child(root)
        picker.present()

        # Crucial: do NOT focus SearchEntry on open.
        self._focus_button_later(close)

    def open_text_editor(self, target, title, placeholder=""):
        """
        Dedicated editor for ordinary text/numeric fields.

        The main form contains buttons rather than Gtk.Entry widgets, so
        swiping the form cannot accidentally summon the keyboard.
        """
        editor = Gtk.ApplicationWindow(application=self)
        editor.set_title(title)
        editor.set_transient_for(self.win)
        editor.set_modal(True)
        editor.set_decorated(False)
        editor.maximize()
        self.touch_window = editor

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(18)
        root.set_margin_end(18)

        heading = Gtk.Label()
        heading.set_markup(f'<span size="19000" weight="bold">{title}</span>')
        heading.set_wrap(True)
        root.append(heading)

        hint = Gtk.Label(
            label="This is the only typing screen. Enter the value, then tap SAVE.",
            xalign=0,
        )
        hint.set_wrap(True)
        root.append(hint)

        entry = Gtk.Entry()
        entry.set_placeholder_text(placeholder)
        entry.set_text(target.get_text())
        entry.set_hexpand(True)
        root.append(entry)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        cancel = Gtk.Button(label="CANCEL")
        cancel.set_hexpand(True)
        cancel.connect("clicked", lambda *_: editor.close())
        buttons.append(cancel)

        clear = Gtk.Button(label="CLEAR")
        clear.set_hexpand(True)

        def do_clear(*_):
            target.set_text("")
            editor.close()

        clear.connect("clicked", do_clear)
        buttons.append(clear)

        save = Gtk.Button(label="SAVE")
        save.set_hexpand(True)
        save.add_css_class("suggested-action")

        def do_save(*_):
            target.set_text(entry.get_text())
            editor.close()

        save.connect("clicked", do_save)
        buttons.append(save)

        root.append(buttons)
        editor.set_child(root)
        editor.present()

        # The user deliberately tapped an editable field, so opening the
        # keyboard here is wanted.
        def focus_entry():
            try:
                entry.grab_focus()
                entry.set_position(-1)
            except Exception:
                pass
            return False

        GLib.idle_add(focus_entry)

    def autocomplete_field(self, kind, placeholder="", text="", game="swsh"):
        app = self

        class PickerField(Gtk.Box):
            def __init__(self):
                super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                self.value = str(text)

                names = {
                    "species": "SELECT SPECIES",
                    "items": "SELECT ITEM",
                    "moves": "SELECT MOVE",
                    "balls": "SELECT BALL",
                }
                self.title = names.get(kind, f"SELECT {kind.upper()}")

                self.button = Gtk.Button()
                self.button.set_hexpand(True)
                self.button.connect("clicked", self.open_picker)
                self.append(self.button)
                self.update_label()

            def update_label(self):
                shown = self.value.strip() or placeholder or "Tap to choose"
                self.button.set_label(f"{shown}   ›")

            def open_picker(self, *_):
                app.open_name_picker(kind, self, self.title, game)

            # Preserve the interface expected by the existing gift builder.
            def get_text(self):
                return self.value

            def set_text(self, value):
                self.value = str(value)
                self.update_label()

            def grab_focus(self):
                return self.button.grab_focus()

        return PickerField()

    def numeric_field(
        self,
        placeholder="Number",
        text="",
        minimum=0,
        maximum=9999999,
        step=1,
        allow_blank=False,
    ):
        """
        Touch-friendly numeric field.

        - Minus/plus work without the keyboard.
        - Tapping the middle value opens the existing dedicated typing screen
          for exact entry.
        - Values are clamped to minimum/maximum.
        """
        app = self

        class NumericField(Gtk.Box):
            def __init__(self):
                super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
                self.minimum = int(minimum)
                self.maximum = int(maximum)
                self.step = max(1, int(step))
                self.allow_blank = bool(allow_blank)
                self.value = str(text).strip()

                self.minus = Gtk.Button(label="−")
                self.minus.set_size_request(44, -1)
                self.minus.connect("clicked", self.adjust, -self.step)
                self.append(self.minus)

                self.value_button = Gtk.Button()
                self.value_button.set_hexpand(True)
                self.value_button.connect("clicked", self.edit)
                self.append(self.value_button)

                self.plus = Gtk.Button(label="+")
                self.plus.set_size_request(44, -1)
                self.plus.connect("clicked", self.adjust, self.step)
                self.append(self.plus)

                self.update_label()

            def _number(self):
                raw = self.value.strip().replace(",", "")
                if not raw:
                    return None
                try:
                    return int(raw)
                except ValueError:
                    return None

            def _clamp(self, number):
                return max(self.minimum, min(self.maximum, int(number)))

            def adjust(self, _button, delta):
                current = self._number()

                if current is None:
                    # Blank quantity rows become a sensible first value.
                    current = self.minimum if delta >= 0 else self.maximum
                else:
                    current = self._clamp(current + int(delta))

                self.value = str(current)
                self.update_label()

            def edit(self, *_):
                app.open_numeric_editor(
                    self,
                    placeholder or "EDIT NUMBER",
                    self.minimum,
                    self.maximum,
                    self.allow_blank,
                )

            def update_label(self):
                raw = self.value.strip()
                shown = raw if raw else ("—" if self.allow_blank else str(self.minimum))
                self.value_button.set_label(f"{shown}   ✎")

            def get_text(self):
                return self.value

            def set_text(self, value):
                raw = str(value).strip()

                if not raw and self.allow_blank:
                    self.value = ""
                    self.update_label()
                    return

                try:
                    number = int(raw.replace(",", ""))
                    self.value = str(self._clamp(number))
                except ValueError:
                    self.value = raw

                self.update_label()

            def grab_focus(self):
                return self.value_button.grab_focus()

        return NumericField()

    def open_numeric_editor(self, target, title, minimum, maximum, allow_blank=False):
        """
        Exact-number editor opened only when the user taps the center value.
        """
        editor = Gtk.ApplicationWindow(application=self)
        editor.set_title(title)
        editor.set_transient_for(self.win)
        editor.set_modal(True)
        editor.set_decorated(False)
        editor.maximize()
        self.touch_window = editor

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.set_margin_top(14)
        root.set_margin_bottom(14)
        root.set_margin_start(18)
        root.set_margin_end(18)

        heading = Gtk.Label()
        heading.set_markup(f'<span size="19000" weight="bold">{title}</span>')
        heading.set_wrap(True)
        root.append(heading)

        hint = Gtk.Label(
            label=f"Allowed range: {minimum:,} – {maximum:,}. "
                  "Use − / + on the main screen for quick changes.",
            xalign=0,
        )
        hint.set_wrap(True)
        root.append(hint)

        entry = Gtk.Entry()
        entry.set_placeholder_text(str(minimum))
        entry.set_text(target.get_text())
        entry.set_hexpand(True)
        # Ask GTK/mobile keyboards for numeric input where supported.
        try:
            entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        except Exception:
            pass
        root.append(entry)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)

        cancel = Gtk.Button(label="CANCEL")
        cancel.set_hexpand(True)
        cancel.connect("clicked", lambda *_: editor.close())
        buttons.append(cancel)

        if allow_blank:
            clear = Gtk.Button(label="CLEAR")
            clear.set_hexpand(True)

            def do_clear(*_):
                target.set_text("")
                editor.close()

            clear.connect("clicked", do_clear)
            buttons.append(clear)

        save = Gtk.Button(label="SAVE")
        save.set_hexpand(True)
        save.add_css_class("suggested-action")

        def do_save(*_):
            raw = entry.get_text().strip().replace(",", "")

            if not raw:
                if allow_blank:
                    target.set_text("")
                    editor.close()
                    return
                raw = str(minimum)

            try:
                number = int(raw)
            except ValueError:
                self.set_status(f"{title}: enter a whole number.")
                return

            number = max(int(minimum), min(int(maximum), number))
            target.set_text(str(number))
            editor.close()

        save.connect("clicked", do_save)
        buttons.append(save)

        root.append(buttons)
        editor.set_child(root)
        editor.present()

        def focus_entry():
            try:
                entry.grab_focus()
                entry.set_position(-1)
            except Exception:
                pass
            return False

        GLib.idle_add(focus_entry)

    def field(self, placeholder="", text=""):
        app = self

        class TapEditField(Gtk.Box):
            def __init__(self):
                super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
                self.value = str(text)
                self.button = Gtk.Button()
                self.button.set_hexpand(True)
                self.button.connect("clicked", self.edit)
                self.append(self.button)
                self.update_label()

            def update_label(self):
                shown = self.value.strip() or placeholder or "Tap to edit"
                self.button.set_label(f"{shown}   ✎")

            def edit(self, *_):
                title = placeholder or "EDIT VALUE"
                app.open_text_editor(self, title, placeholder)

            def get_text(self):
                return self.value

            def set_text(self, value):
                self.value = str(value)
                self.update_label()

            def grab_focus(self):
                return self.button.grab_focus()

        return TapEditField()

    def labeled(self, label, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        l = Gtk.Label(label=label, xalign=0)
        l.set_size_request(92, -1)
        widget.set_hexpand(True)
        row.append(l)
        row.append(widget)
        return row

    def resolve_name(self, kind, value, optional=False):
        raw = value.strip()
        if not raw:
            return 0 if optional else None
        if raw.isdigit():
            return int(raw)

        cache_key = ("swsh", kind)
        if cache_key not in self.name_cache:
            self.name_cache[cache_key] = pokemon.SERVICE.names("swsh", kind)
        needle = raw.casefold().replace(" ", "").replace("-", "").replace(".", "")
        for item in self.name_cache[cache_key]:
            name = str(item["name"])
            norm = name.casefold().replace(" ", "").replace("-", "").replace(".", "")
            if norm == needle:
                return int(item["id"])
        return None

    def build_scroll_page(self, title, back_cb):
        outer = self.page(title, back_cb)
        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        try:
            sc.set_kinetic_scrolling(True)
            sc.set_overlay_scrolling(True)
        except Exception:
            pass
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.set_margin_end(2)
        sc.set_child(col)
        outer.append(sc)
        self.win.set_child(outer)
        return outer, col

    def show_gift_builder(self, kind):
        outer, col = self.build_scroll_page(
            f"BUILD GIFT • {dict((k,l) for k,l,_ in swgift.KINDS)[kind].upper()}",
            self.show_gift_build_menu
        )
        state = swgift.blank(kind=kind)

        card = self.numeric_field("Card ID", "9999", 1, 65535, 1)
        widgets = {"card_id": card}

        if kind in ("pokemon", "egg"):
            species = self.autocomplete_field("species", "Species name or ID", "Pikachu")
            level = self.numeric_field("Level", "25" if kind == "pokemon" else "1", 1, 100, 1)
            col.append(self.labeled("Species", species))
            col.append(self.labeled("Level", level))
            widgets.update(species=species, level=level)

            if kind == "pokemon":
                nickname = self.field("Nickname (optional)", "")
                ot = self.field("OT (optional)", str(TRAINERS["swsh"]["ot"]))
                item = self.autocomplete_field("items", "Held item name/ID", "")

                nature = Gtk.DropDown.new_from_strings([
                    "Random",
                    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
                    "Bold", "Docile", "Relaxed", "Impish", "Lax",
                    "Timid", "Hasty", "Serious", "Jolly", "Naive",
                    "Modest", "Mild", "Quiet", "Bashful", "Rash",
                    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
                ])
                nature.set_selected(0)

                ball = self.autocomplete_field(
                    "balls",
                    "Ball name or ID (blank = default)",
                    ""
                )

                shiny = Gtk.CheckButton(label="Shiny")
                gmax = Gtk.CheckButton(label="Gigantamax")

                col.append(self.labeled("Nickname", nickname))
                col.append(self.labeled("OT", ot))
                col.append(self.labeled("Held item", item))
                col.append(self.labeled("Nature", nature))
                col.append(self.labeled("Ball", ball))
                col.append(shiny)
                col.append(gmax)

                widgets.update(
                    nickname=nickname,
                    ot=ot,
                    item=item,
                    nature=nature,
                    ball=ball,
                    shiny=shiny,
                    gmax=gmax
                )

            moves = []
            for n in range(4):
                e = self.autocomplete_field("moves", f"Move {n+1} name or ID", "")
                col.append(self.labeled(f"Move {n+1}", e))
                moves.append(e)
            widgets["moves"] = moves

        elif kind == "items":
            rows = []
            defaults = [("Master Ball", "1"), ("", ""), ("", ""), ("", ""), ("", ""), ("", "")]
            for n, (it, qty) in enumerate(defaults, 1):
                item = self.autocomplete_field("items", "Item name or ID", it)
                amount = self.numeric_field("Quantity", qty, 1, 999, 1, allow_blank=True)
                row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                lbl = Gtk.Label(label=f"{n}.", xalign=0)
                lbl.set_size_request(24, -1)
                item.set_hexpand(True)
                amount.set_size_request(190, -1)
                row.append(lbl)
                row.append(item)
                row.append(amount)
                col.append(row)
                rows.append((item, amount))
            widgets["items"] = rows

        elif kind == "clothing":
            checks = []
            for outfit in swgift.OUTFITS:
                cb = Gtk.CheckButton(label=outfit.label)
                col.append(cb)
                checks.append((outfit.key, cb))
            widgets["outfits"] = checks

        elif kind == "bp":
            bp = self.numeric_field("Battle Points", "10", 1, 9999, 10)
            col.append(self.labeled("Battle Points", bp))
            widgets["bp"] = bp

        elif kind == "money":
            money = self.numeric_field("Money", "100000", 1, 9999999, 10000)
            col.append(self.labeled("Money", money))
            widgets["money"] = money

        col.append(self.labeled("Card ID", card))

        summary = Gtk.Label(label="")
        summary.set_wrap(True)
        col.append(summary)

        send = Gtk.Button(label="BUILD & SEND GIFT")
        send.add_css_class("suggested-action")
        send.connect("clicked", self.send_custom_gift, kind, widgets, summary)
        col.append(send)

    def compile_custom_gift(self, state):
        # Everything except explicit Nature uses pokeldn's normal builder.
        if state.get("kind") != "pokemon" or "nature" not in state:
            return swgift.compile(state)

        raw = bytearray(swgift.record(state))

        nature_offset, _fmt = wc8.POKEMON["nature"]
        raw[nature_offset] = int(state["nature"]) & 0xFF

        # Recalculate the Wonder Card checksum.
        raw = wc8.seal(raw)

        name = state.get("nickname") or "Pokemon"

        return gift_file.from_record(
            raw,
            name=name
        )

    def send_custom_gift(self, button, kind, w, summary):
        try:
            state = swgift.blank(kind=kind)
            state["card_id"] = entry_int(w["card_id"], 9999)

            if kind in ("pokemon", "egg"):
                sid = self.resolve_name("species", w["species"].get_text())
                if sid is None:
                    raise ValueError("Unknown species name.")
                state["species"] = sid
                state["level"] = entry_int(w["level"], 1 if kind == "egg" else 25)
                state["moves"] = []
                for e in w["moves"]:
                    raw = e.get_text().strip()
                    if not raw:
                        state["moves"].append(0)
                    else:
                        mid = self.resolve_name("moves", raw)
                        if mid is None:
                            raise ValueError(f"Unknown move: {raw}")
                        state["moves"].append(mid)

                if kind == "pokemon":
                    state["nickname"] = w["nickname"].get_text().strip()
                    state["ot"] = w["ot"].get_text().strip()
                    raw_item = w["item"].get_text().strip()
                    if raw_item:
                        iid = self.resolve_name("items", raw_item)
                        if iid is None:
                            raise ValueError(f"Unknown held item: {raw_item}")
                        state["item"] = iid
                    else:
                        state["item"] = 0
                    nature_index = w["nature"].get_selected()

                    # Dropdown 0 = Random.
                    # Nature IDs are 0..24, so UI index is ID + 1.
                    if nature_index > 0:
                        state["nature"] = nature_index - 1

                    raw_ball = w["ball"].get_text().strip()

                    if raw_ball:
                        ball_id = self.resolve_name("balls", raw_ball)

                        if ball_id is None:
                            raise ValueError(
                                f"Unknown ball: {raw_ball}"
                            )

                        state["ball"] = int(ball_id)
                    else:
                        state["ball"] = 0

                    state["shiny"] = w["shiny"].get_active()
                    state["gigantamax"] = w["gmax"].get_active()

            elif kind == "items":
                pairs = []
                for item_e, qty_e in w["items"]:
                    raw = item_e.get_text().strip()
                    if not raw:
                        continue
                    iid = self.resolve_name("items", raw)
                    if iid is None:
                        raise ValueError(f"Unknown item: {raw}")
                    qty = entry_int(qty_e, 1)
                    pairs.append([iid, qty])
                state["items"] = pairs

            elif kind == "clothing":
                state["outfits"] = [key for key, cb in w["outfits"] if cb.get_active()]

            elif kind == "bp":
                state["bp"] = entry_int(w["bp"], 10)

            elif kind == "money":
                state["money"] = entry_int(w["money"], 100000)

            when, lines = swgift.describe(
                state,
                lambda typ, n: self.lookup_name_for_summary(typ, n)
            )
            summary.set_text(when + "\n" + "\n".join(lines))
            gift = self.compile_custom_gift(state)
            self.save_and_host_gift(
                gift,
                dict((k,l) for k,l,_ in swgift.KINDS)[kind]
            )
        except Exception as exc:
            summary.set_text(f"ERROR: {exc}")
            self.set_status(f"Gift build failed: {exc}")

    def lookup_name_for_summary(self, kind, number):
        if not number:
            return f"{kind} #{number}"
        names_kind = "species" if kind == "species" else "items"
        try:
            if ("swsh", names_kind) not in self.name_cache:
                self.name_cache[("swsh", names_kind)] = pokemon.SERVICE.names("swsh", names_kind)
            return next((x["name"] for x in self.name_cache[("swsh", names_kind)]
                         if int(x["id"]) == int(number)), f"{kind} #{number}")
        except Exception:
            return f"{kind} #{number}"

    def open_gift_file(self, *_):
        chooser = Gtk.FileChooserNative.new(
            "Open Sword/Shield gift",
            self.win,
            Gtk.FileChooserAction.OPEN,
            "Open",
            "Cancel",
        )
        filt = Gtk.FileFilter()
        filt.set_name("Sword/Shield Mystery Gift")
        filt.add_pattern("*.pokegift")
        filt.add_pattern("*.wc8")
        chooser.add_filter(filt)
        chooser.connect("response", self.gift_file_response)
        chooser.show()

    def gift_file_response(self, chooser, response):
        if response == Gtk.ResponseType.ACCEPT:
            f = chooser.get_file()
            path = f.get_path()
            try:
                gift = gifts.load(path, game="swsh")
                # Re-save as .pokegift so the host gets one predictable format.
                self.save_and_host_gift(gift, Path(path).name)
            except Exception as exc:
                self.set_status(f"Could not open gift: {exc}")
        chooser.destroy()
    # ---------- FireRed placeholder ----------

    # ---------- FireRed / LeafGreen ----------

    def show_frlg(self, *_):
        box = self.page("FIRE RED / LEAF GREEN", self.show_home)
        fr = TRAINERS["frlg"]
        info = Gtk.Label(
            label=f"Configured: {FRLG_VERSION.title()} • {fr['ot']} • "
                  f"TID {fr['tid']} • SID {fr['sid']}"
        )
        info.set_wrap(True)
        box.append(info)
        box.append(self.button("SHOWDOWN TRADE", self.show_frlg_trade))
        box.append(self.button("MYSTERY GIFT", self.show_frlg_gifts))
        box.append(self.button("WONDER NEWS", self.show_frlg_news))
        box.append(self.button("READ SAVE / TRAINER INFO", self.show_frlg_read))
        self.win.set_child(box)

    def show_frlg_trade(self, *_):
        self.showdown_editor(
            "FIRE RED • DIRECT CORNER TRADE",
            "frlg",
            self.host_frlg_trade,
            self.show_frlg,
        )

    def host_frlg_trade(self, button, view):
        text = text_of(view)
        if not text:
            self.set_status("Add or paste at least one Gen III Pokémon first.")
            return
        try:
            infos = self.showdown_files("frlg", text)
        except ValueError as exc:
            self.set_status(f"Build failed: {exc}")
            return

        # Direct Corner requires at least two host party members.
        # With only one selected Pokémon we keep the proven filler + offer
        # layout. With 2–6 selected Pokémon, use the selected party directly.
        if len(infos) == 1:
            try:
                filler = pokemon.SERVICE.make(
                    "frlg",
                    25,
                    TRAINERS["frlg"],
                    level=5,
                    shiny=False,
                    options={"ivs": {k: 31 for k in STATS}},
                )
            except pokemon.BuilderError as exc:
                self.set_status(f"Could not build host party: {exc}")
                return

            party = [filler, infos[0]]
            offer_slot = "1"
        else:
            party = infos[:6]
            offer_slot = "0"

        cmd = [
            PYTHON, "-u", REPO / "bin/frlg_trade_host.py",
            "--keys", KEYS,
            "--ot", str(TRAINERS["frlg"]["ot"]),
            "--version", FRLG_VERSION,
            "--id", f"{TRAINERS['frlg']['tid']}:{TRAINERS['frlg']['sid']}",
            "--slot", offer_slot,
            "-o", APP_DIR / "received-frlg.pk3",
        ]
        cmd += [info["file"] for info in party]

        self.launch(
            cmd,
            f"FireRed Direct Corner • {len(party)} party Pokémon"
        )

    def show_frlg_gifts(self, *_):
        box = self.page("FIRE RED • MYSTERY GIFT", self.show_frlg)
        hint = Gtk.Label(
            label="FireRed: Mystery Gift → Wonder Cards → Friend. Search and tap a gift."
        )
        hint.set_wrap(True)
        box.append(hint)

        search = Gtk.SearchEntry()
        search.set_placeholder_text("Search Celebi, Master Ball, egg, event...")
        box.append(search)

        count = Gtk.Label(xalign=0)
        box.append(count)

        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        sc.set_child(col)
        box.append(sc)

        presets = [
            p for p in frgift.PRESETS
            if getattr(p, "args", ()) and p.args[0] == "--gift"
        ]

        def render(*_):
            child = col.get_first_child()
            while child:
                nxt = child.get_next_sibling()
                col.remove(child)
                child = nxt
            words = search.get_text().casefold().split()
            shown = [
                p for p in presets
                if all(w in f"{p.label} {p.group} {p.summary}".casefold() for w in words)
            ]
            count.set_text(f"{len(shown)} of {len(presets)} gifts")
            for preset in shown:
                b = Gtk.Button(label=f"{preset.label}\n{preset.group} • {preset.summary}")
                b.connect("clicked", self.host_frlg_preset, preset.key)
                col.append(b)

        search.connect("search-changed", render)
        render()
        self.win.set_child(box)

    def host_frlg_preset(self, button, key):
        preset = frgift.PRESET[key]
        cmd = [
            PYTHON, "-u", REPO / "bin/frlg_mg_host.py",
            "--live", "--keys", KEYS,
            "--expect-console", FRLG_VERSION,
            *preset.args,
        ]
        self.launch(cmd, f"FireRed Mystery Gift • {preset.label}")

    def show_frlg_news(self, *_):
        box = self.page("FIRE RED • WONDER NEWS", self.show_frlg)
        hint = Gtk.Label(
            label="FireRed: Mystery Gift → Wonder News → Friend. "
                  "Use a different News ID later if you want the same text accepted again."
        )
        hint.set_wrap(True)
        box.append(hint)

        for preset in frgift.PRESETS:
            if getattr(preset, "args", ()) and preset.args[0] == "--news":
                b = Gtk.Button(label=f"{preset.label}\n{preset.summary}")
                b.connect("clicked", self.host_frlg_news, preset.key)
                box.append(b)
        self.win.set_child(box)

    def host_frlg_news(self, button, key):
        preset = frgift.PRESET[key]
        cmd = [
            PYTHON, "-u", REPO / "bin/frlg_mg_host.py",
            "--live", "--keys", KEYS,
            "--expect-console", FRLG_VERSION,
            *preset.args,
        ]
        self.launch(cmd, f"FireRed Wonder News • {preset.label}")

    def show_frlg_read(self, *_):
        box = self.page("FIRE RED • READ SAVE", self.show_frlg)
        hint = Gtk.Label(
            label="Read-only. FireRed: Mystery Gift → Wonder Cards → Friend. "
                  "After the dump is written, tap STOP, then VIEW."
        )
        hint.set_wrap(True)
        box.append(hint)
        box.append(self.button("READ TRAINER INFO", self.start_frlg_read_trainer))
        box.append(self.button("VIEW TRAINER INFO", self.view_frlg_trainer))
        box.append(self.button("READ SAVED PARTY", self.start_frlg_read_party))
        box.append(self.button("VIEW SAVED PARTY", self.view_frlg_party))
        self.win.set_child(box)

    def start_frlg_read_trainer(self, *_):
        path = APP_DIR / "frlg-sav2.bin"
        cmd = [
            PYTHON, "-u", REPO / "bin/frlg_mg_host.py",
            "--live", "--keys", KEYS,
            "--expect-console", FRLG_VERSION,
            "--buffer-script", "save-dump",
            "--dump-block", "sav2",
            "--dump-size", "64",
            "--dump-file", path,
        ]
        self.launch(cmd, "FireRed reading trainer info")

    def start_frlg_read_party(self, *_):
        path = APP_DIR / "frlg-party.bin"
        cmd = [
            PYTHON, "-u", REPO / "bin/frlg_mg_host.py",
            "--live", "--keys", KEYS,
            "--expect-console", FRLG_VERSION,
            "--buffer-script", "save-dump",
            "--dump-block", "sav1",
            "--dump-offset", "0x34",
            "--dump-size", "608",
            "--dump-file", path,
        ]
        self.launch(cmd, "FireRed reading saved party")

    def _show_frlg_dump(self, title, path, block, offset=None):
        box = self.page(title, self.show_frlg_read)
        path = Path(path)
        if not path.exists():
            box.append(Gtk.Label(label="No dump has been saved yet."))
            self.win.set_child(box)
            return

        cmd = [
            str(PYTHON), str(REPO / "tools/frlg/dump_read.py"),
            str(path), "--block", block,
        ]
        if offset is not None:
            cmd += ["--offset", offset]

        result = subprocess.run(
            cmd, cwd=str(REPO), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )

        view = Gtk.TextView()
        view.set_editable(False)
        view.set_monospace(True)
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.get_buffer().set_text(result.stdout.strip() or "No output.")

        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        sc.set_child(view)
        box.append(sc)
        self.win.set_child(box)

    def view_frlg_trainer(self, *_):
        self._show_frlg_dump(
            "FIRE RED • TRAINER INFO",
            APP_DIR / "frlg-sav2.bin",
            "sav2",
        )

    def view_frlg_party(self, *_):
        self._show_frlg_dump(
            "FIRE RED • SAVED PARTY",
            APP_DIR / "frlg-party.bin",
            "sav1",
            "0x34",
        )

    # ---------- settings ----------

    def _pokeldn_version(self):
        try:
            result = subprocess.run(
                ["git", "describe", "--tags", "--always", "--dirty"],
                cwd=str(REPO),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            return result.stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    def _friendship_patch_active(self):
        try:
            source = (REPO / "services/pkhex/Program.cs").read_text(
                encoding="utf-8",
                errors="ignore",
            )
            return (
                "CurrentFriendship = friendship" in source
                and 'Number("friendship")' in source
            )
        except Exception:
            return False

    def _species_status(self):
        games = [
            ("frlg", "FireRed / LeafGreen"),
            ("lgpe", "Let's Go Pikachu / Eevee"),
            ("swsh", "Sword / Shield"),
            ("bdsp", "Brilliant Diamond / Shining Pearl"),
            ("pla", "Legends: Arceus"),
            ("sv", "Scarlet / Violet"),
            ("za", "Legends Z-A"),
        ]

        rows = []
        pkhex_ok = False

        for game, label in games:
            try:
                count = len(pokemon.SERVICE.species(game))
                rows.append((label, f"{count} species"))
                pkhex_ok = True
            except Exception as exc:
                rows.append((label, f"ERROR: {exc}"))

        return pkhex_ok, rows

    def show_settings(self, *_):
        box = self.page("SETTINGS / STATUS", self.show_home)

        sc = Gtk.ScrolledWindow()
        sc.set_vexpand(True)
        try:
            sc.set_kinetic_scrolling(True)
            sc.set_overlay_scrolling(True)
        except Exception:
            pass

        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        col.set_margin_end(5)

        version = self._pokeldn_version()
        radio_device = self._serial_radio_device()
        radio_ok = radio_device is not None
        patch_ok = self._friendship_patch_active()
        pkhex_ok, species_rows = self._species_status()

        summary = Gtk.Label(
            label=(
                f"pokeldn: {version}\n"
                f"PKHeX service: {'OK' if pkhex_ok else 'ERROR'}\n"
                f"Friendship / Happiness patch: "
                f"{'ACTIVE' if patch_ok else 'NOT DETECTED'}\n"
                f"ESP32 radio: {'CONNECTED' if radio_ok else 'NOT FOUND'}"
            ),
            xalign=0,
        )
        summary.set_wrap(True)
        col.append(summary)

        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        col.append(sep)

        title = Gtk.Label(xalign=0)
        title.set_markup('<span weight="bold" size="15000">PKHeX species catalogs</span>')
        col.append(title)

        for label, value in species_rows:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

            left = Gtk.Label(label=label, xalign=0)
            left.set_hexpand(True)
            left.set_wrap(True)

            right = Gtk.Label(label=value, xalign=1)
            right.set_selectable(True)

            row.append(left)
            row.append(right)
            col.append(row)

        sep2 = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        col.append(sep2)

        trainers = Gtk.Label(
            label=(
                "Configured trainers\n\n"
                f"Z-A\n{TRAINERS['za']['ot']} • raw TID {TRAINERS['za']['tid']} / "
                f"SID {TRAINERS['za']['sid']}\n\n"
                f"Sword / Shield\n{TRAINERS['swsh']['ot']} • raw TID "
                f"{TRAINERS['swsh']['tid']} / SID {TRAINERS['swsh']['sid']}\n\n"
                f"FireRed / LeafGreen\n{TRAINERS['frlg']['ot']} • TID "
                f"{TRAINERS['frlg']['tid']} / SID {TRAINERS['frlg']['sid']}\n\n"
                "Sword Link Trade mode: uncoded\n\n"
                f"Radio setting:\n{RADIO}\n\n"
                f"Resolved radio:\n{radio_device or 'not found'}"
            ),
            xalign=0,
        )
        trainers.set_wrap(True)
        trainers.set_selectable(True)
        col.append(trainers)

        sc.set_child(col)
        box.append(sc)
        self.win.set_child(box)



if __name__ == "__main__":
    TradeBox().run()