#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pythonista tap GUI for the FR/LG EV Training helper.

Keep beside: ev_trainer.py, ev_data.json, trainer_spots.json
Run this file in Pythonista. Text/CLI: ev_trainer.py
"""

import json
import sys
import traceback
from pathlib import Path

try:
    import ui  # type: ignore
except ImportError:
    ui = None

from ev_trainer import (
    STATS, VITAMIN_PRICE, VITAMIN_EV, VITAMIN_CAP,
    MAX_TOTAL_EVS, MAX_PER_STAT_EVS,
    Pokemon, Party, Session, WildSpot, TrainerSpot,
    battles_to_goal, vitamin_strategy, validate_ev_spread,
    format_ev_summary, normalize_stat,
    load_ev_data, load_trainer_spots, save_session, load_session,
    COMMON_SPREADS,
)

HERE = Path(__file__).resolve().parent
SAVE_FILE = HERE / "ev_session.json"
PAD = 8
BTN_H = 36
ROW_H = 44


def _console(msg):
    print("[ev_trainer_gui] " + str(msg))


def _screen_width():
    if ui is None:
        return 320
    try:
        w, _ = ui.get_screen_size()
        return max(280, min(int(w), 430))
    except Exception:
        return 320


def _content_width():
    return _screen_width() - 2 * PAD


def _show_message(title, message):
    _console(title)
    print(message)
    if ui is None:
        return
    v = ui.View(name=title)
    v.background_color = "white"
    sw = _screen_width()
    top = PAD + 44
    header = ui.Label(
        frame=(PAD, PAD + 20, sw - 2 * PAD, 28),
        flex="W",
        font=("<system-bold>", 17),
        text=title,
    )
    tv = ui.TextView(
        frame=(PAD, top, sw - 2 * PAD, 400),
        flex="WH",
        font=("<monospaced>", 11),
        editable=False,
        selectable=True,
    )
    tv.text = message
    v.add_subview(header)
    v.add_subview(tv)
    v.present("fullscreen")


def _make_toggle(titles, selected_index, action, y):
    cw = _content_width()
    n = len(titles)
    gap = 6
    bw = (cw - gap * (n - 1)) / float(n)
    row = ui.View(frame=(PAD, y, cw, BTN_H), flex="W")
    buttons = []
    for i, title in enumerate(titles):
        b = ui.Button(
            title=title,
            frame=(i * (bw + gap), 0, bw, BTN_H),
            font=("<system>", 13),
            border_width=1,
            border_color="#CCCCCC",
            corner_radius=6,
            action=action,
        )
        b.name = "toggle_%d" % i
        row.add_subview(b)
        buttons.append(b)

    def paint(idx):
        for i, b in enumerate(buttons):
            on = i == idx
            b.background_color = "#007AFF" if on else "#F2F2F7"
            b.tint_color = "white" if on else "#111111"

    paint(selected_index)
    row.paint = paint
    row.buttons = buttons
    return row


class EVTrainerApp:
    def __init__(self):
        self.ev_data = {}
        self.trainer_spots = []
        self.session = Session()
        self.version = "firered"
        self.nav = None
        self._load_data()

    def _load_data(self):
        try:
            self.ev_data = load_ev_data()
            _console(f"Loaded {len(self.ev_data.get('species_evs', {}))} species")
        except Exception as e:
            _console(f"Failed to load ev_data: {e}")
            self.ev_data = {"species_evs": {}, "best_spots": {}, "wild_spots": []}

        try:
            self.trainer_spots = load_trainer_spots()
            _console(f"Loaded {len(self.trainer_spots)} trainer spots")
        except Exception as e:
            _console(f"Failed to load trainer_spots: {e}")
            self.trainer_spots = []

        saved = load_session(SAVE_FILE)
        if saved:
            self.session = saved
            _console(f"Restored session with {len(self.session.party.pokemon)} pokemon")

    def _save_session(self):
        try:
            save_session(self.session, SAVE_FILE)
        except Exception as e:
            _console(f"Failed to save session: {e}")

    def run(self):
        if ui is None:
            print("No ui module - run in Pythonista")
            return
        root = self._make_main_menu()
        self.nav = ui.NavigationView(root)
        self.nav.present("fullscreen")

    def _make_main_menu(self):
        v = ui.View(name="EV Trainer", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        money_lbl = ui.Label(
            frame=(PAD, y, cw, 24),
            flex="W",
            font=("<system>", 14),
            text_color="#333333",
        )
        money_lbl.text = f"¥{self.session.party.money:,}"
        v.add_subview(money_lbl)
        v.money_label = money_lbl
        y += 30

        items_lbl = ui.Label(
            frame=(PAD, y, cw, 20),
            flex="W",
            font=("<system>", 12),
            text_color="#666666",
        )
        items = []
        if self.session.party.amulet_coin_holder:
            items.append("Amulet Coin")
        if self.session.party.exp_share_holder is not None:
            items.append("Exp Share")
        items_lbl.text = ", ".join(items) if items else "No held items"
        v.add_subview(items_lbl)
        y += 30

        menu_items = [
            ("Party Setup", self._show_party),
            ("Spot Finder", self._show_spot_finder),
            ("Training Session", self._show_training),
            ("Settings", self._show_settings),
        ]

        for title, action in menu_items:
            btn = ui.Button(
                title=title,
                frame=(PAD, y, cw, BTN_H),
                font=("<system>", 16),
                border_width=1,
                border_color="#007AFF",
                corner_radius=8,
                action=action,
            )
            btn.tint_color = "#007AFF"
            v.add_subview(btn)
            y += BTN_H + 10

        return v

    def _refresh_main_menu(self):
        if self.nav and len(self.nav.subviews) > 0:
            root = self.nav.subviews[0]
            if hasattr(root, "money_label"):
                root.money_label.text = f"¥{self.session.party.money:,}"

    def _show_party(self, sender):
        v = ui.View(name="Party", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        add_btn = ui.Button(
            title="+ Add Pokémon",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
            action=self._add_pokemon,
        )
        add_btn.tint_color = "#34C759"
        v.add_subview(add_btn)
        y += BTN_H + 10

        tv = ui.TableView(frame=(PAD, y, cw, 300), flex="WH")
        tv.allows_selection = True
        ds = ui.ListDataSource(self._party_items())
        ds.action = self._on_party_select
        ds.delete_enabled = True
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)
        v.table_view = tv
        v.data_source = ds

        self.nav.push_view(v)

    def _party_items(self):
        items = []
        for i, mon in enumerate(self.session.party.pokemon):
            remaining = mon.total_remaining()
            status = "✓" if mon.is_complete() else f"{remaining} EVs left"
            brace = " [MB]" if mon.using_macho_brace else ""
            items.append({
                "title": f"{mon.name}{brace}\n{status}",
                "accessory_type": "disclosure_indicator",
            })
        return items

    def _on_party_select(self, sender):
        idx = sender.selected_row
        if 0 <= idx < len(self.session.party.pokemon):
            self._edit_pokemon(idx)

    def _add_pokemon(self, sender):
        if len(self.session.party.pokemon) >= 6:
            _show_message("Party Full", "Maximum 6 Pokémon")
            return
        self._show_pokemon_editor(None)

    def _edit_pokemon(self, index):
        self._show_pokemon_editor(index)

    def _show_pokemon_editor(self, index):
        is_new = index is None
        mon = Pokemon("") if is_new else self.session.party.pokemon[index]

        v = ui.View(name="Edit Pokémon" if not is_new else "Add Pokémon", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        name_field = ui.TextField(
            frame=(PAD, y, cw, 32),
            placeholder="Pokémon name",
            font=("<system>", 16),
        )
        name_field.text = mon.name
        v.add_subview(name_field)
        y += 40

        preset_btn = ui.Button(
            title="Use Preset Spread",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
        )
        preset_btn.tint_color = "#5856D6"
        v.add_subview(preset_btn)
        y += BTN_H + 10

        stat_fields = {}
        for stat in STATS:
            lbl = ui.Label(
                frame=(PAD, y, 70, 28),
                text=stat,
                font=("<system>", 14),
            )
            v.add_subview(lbl)

            target_field = ui.TextField(
                frame=(80, y, 60, 28),
                placeholder="0",
                keyboard_type=ui.KEYBOARD_NUMBER_PAD,
            )
            target_field.text = str(mon.target_evs.get(stat, 0))
            v.add_subview(target_field)

            current_field = ui.TextField(
                frame=(150, y, 60, 28),
                placeholder="0",
                keyboard_type=ui.KEYBOARD_NUMBER_PAD,
            )
            current_field.text = str(mon.current_evs.get(stat, 0))
            v.add_subview(current_field)

            stat_fields[stat] = (target_field, current_field)
            y += 34

        brace_switch = ui.Switch(frame=(PAD, y, 60, 30))
        brace_switch.value = mon.using_macho_brace
        v.add_subview(brace_switch)
        brace_lbl = ui.Label(
            frame=(70, y, cw - 70, 28),
            text="Macho Brace (2× EVs)",
            font=("<system>", 14),
        )
        v.add_subview(brace_lbl)
        y += 40

        def save_pokemon(sender):
            name = name_field.text.strip()
            if not name:
                _show_message("Error", "Name required")
                return

            target = {}
            current = {}
            for stat, (tf, cf) in stat_fields.items():
                try:
                    target[stat] = int(tf.text or "0")
                    current[stat] = int(cf.text or "0")
                except ValueError:
                    target[stat] = 0
                    current[stat] = 0

            errors = validate_ev_spread(target)
            if errors:
                _show_message("Invalid Spread", "\n".join(errors))
                return

            new_mon = Pokemon(name, target, current, brace_switch.value)

            if is_new:
                self.session.party.add_pokemon(new_mon)
            else:
                self.session.party.pokemon[index] = new_mon

            self._save_session()
            self.nav.pop_view()

        save_btn = ui.Button(
            title="Save",
            frame=(PAD, y, cw, BTN_H),
            font=("<system-bold>", 16),
            action=save_pokemon,
        )
        save_btn.tint_color = "#007AFF"
        save_btn.background_color = "#E8F0FE"
        save_btn.corner_radius = 8
        v.add_subview(save_btn)

        def show_presets(sender):
            self._show_preset_picker(stat_fields)

        preset_btn.action = show_presets

        self.nav.push_view(v)

    def _show_preset_picker(self, stat_fields):
        v = ui.View(name="Presets", background_color="white")
        sw = _screen_width()
        cw = _content_width()

        items = [{"title": name, "accessory_type": "disclosure_indicator"} for name, _ in COMMON_SPREADS]
        tv = ui.TableView(frame=(PAD, PAD + 50, cw, 400), flex="WH")
        ds = ui.ListDataSource(items)

        def on_select(sender):
            idx = sender.selected_row
            if 0 <= idx < len(COMMON_SPREADS):
                _, spread = COMMON_SPREADS[idx]
                for stat in STATS:
                    val = spread.get(stat, 0)
                    if stat in stat_fields:
                        stat_fields[stat][0].text = str(val)
                self.nav.pop_view()

        ds.action = on_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)
        self.nav.push_view(v)

    def _show_spot_finder(self, sender):
        v = ui.View(name="Spot Finder", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        stat_items = [{"title": stat, "accessory_type": "disclosure_indicator"} for stat in STATS]
        tv = ui.TableView(frame=(PAD, y, cw, 350), flex="WH")
        ds = ui.ListDataSource(stat_items)

        def on_stat_select(sender):
            idx = sender.selected_row
            if 0 <= idx < len(STATS):
                self._show_spots_for_stat(STATS[idx])

        ds.action = on_stat_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)

        self.nav.push_view(v)

    def _show_spots_for_stat(self, stat):
        v = ui.View(name=f"{stat} Spots", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        toggle = _make_toggle(["Wild", "Trainer", "Both"], 2, self._on_spot_type_toggle, y)
        v.add_subview(toggle)
        v.spot_toggle = toggle
        y += BTN_H + 10

        tv = ui.TableView(frame=(PAD, y, cw, 350), flex="WH")
        v.add_subview(tv)
        v.table_view = tv
        v.current_stat = stat

        self._refresh_spot_list(v, "both")
        self.nav.push_view(v)

    def _on_spot_type_toggle(self, sender):
        idx = int(sender.name.split("_")[1])
        parent = sender.superview.superview
        parent.spot_toggle.paint(idx)
        spot_type = ["wild", "trainer", "both"][idx]
        self._refresh_spot_list(parent, spot_type)

    def _refresh_spot_list(self, view, spot_type):
        stat = view.current_stat
        items = []

        best = self.ev_data.get("best_spots", {}).get(stat, [])
        if spot_type in ("wild", "both"):
            for spot in best[:8]:
                loc = spot.get("location", "?")
                purity = spot.get("purity", 0)
                ev_rate = spot.get("ev_rate", 0)
                pokemon = spot.get("pokemon", [])
                species_str = ", ".join(p["species"].title() for p in pokemon[:2])
                items.append({
                    "title": f"[W] {loc}\n{purity}% pure, {ev_rate:.1f} EV/enc — {species_str}",
                })

        if spot_type in ("trainer", "both"):
            trainer_items = []
            for t in self.trainer_spots:
                evs = t.total_evs(stat)
                if evs > 0:
                    money = t.money_reward(self.session.party.amulet_coin_holder)
                    trainer_items.append((evs, money, t))
            trainer_items.sort(key=lambda x: (-x[0], -x[1]))
            for evs, money, t in trainer_items[:6]:
                items.append({
                    "title": f"[T] {t.location} - {t.trainer_name}\n{evs} EVs, ¥{money:,}",
                })

        ds = ui.ListDataSource(items if items else [{"title": "No spots found"}])
        view.table_view.data_source = view.table_view.delegate = ds
        view.table_view.reload()

    def _show_training(self, sender):
        if not self.session.party.pokemon:
            _show_message("No Party", "Add Pokémon in Party Setup first")
            return

        v = ui.View(name="Training", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        active = self.session.active_pokemon
        if not active:
            self.session.active_index = 0
            active = self.session.active_pokemon

        name_lbl = ui.Label(
            frame=(PAD, y, cw, 28),
            font=("<system-bold>", 18),
            text=active.name if active else "None",
        )
        v.add_subview(name_lbl)
        v.name_label = name_lbl
        y += 34

        ev_text = ui.TextView(
            frame=(PAD, y, cw, 150),
            font=("<monospaced>", 12),
            editable=False,
        )
        ev_text.text = format_ev_summary(active) if active else ""
        v.add_subview(ev_text)
        v.ev_text = ev_text
        y += 160

        money_lbl = ui.Label(
            frame=(PAD, y, cw, 24),
            font=("<system>", 14),
            text=f"¥{self.session.party.money:,}",
        )
        v.add_subview(money_lbl)
        v.money_label = money_lbl
        y += 30

        ko_btn = ui.Button(
            title="Record KO (+1 EV)",
            frame=(PAD, y, cw // 2 - 5, BTN_H),
            font=("<system>", 14),
            action=lambda s: self._record_quick_ko(v),
        )
        ko_btn.tint_color = "#34C759"
        ko_btn.border_width = 1
        ko_btn.border_color = "#34C759"
        ko_btn.corner_radius = 6
        v.add_subview(ko_btn)

        species_btn = ui.Button(
            title="Select Species",
            frame=(PAD + cw // 2 + 5, y, cw // 2 - 5, BTN_H),
            font=("<system>", 14),
            action=lambda s: self._show_species_picker(v),
        )
        species_btn.tint_color = "#5856D6"
        species_btn.border_width = 1
        species_btn.border_color = "#5856D6"
        species_btn.corner_radius = 6
        v.add_subview(species_btn)
        y += BTN_H + 10

        vit_btn = ui.Button(
            title=f"Use Vitamin (¥{VITAMIN_PRICE:,})",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
            action=lambda s: self._show_vitamin_picker(v),
        )
        vit_btn.tint_color = "#FF9500"
        vit_btn.border_width = 1
        vit_btn.border_color = "#FF9500"
        vit_btn.corner_radius = 6
        v.add_subview(vit_btn)
        y += BTN_H + 10

        switch_btn = ui.Button(
            title="Switch Active Pokémon",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
            action=lambda s: self._show_active_picker(v),
        )
        switch_btn.tint_color = "#007AFF"
        v.add_subview(switch_btn)

        self.nav.push_view(v)

    def _record_quick_ko(self, view):
        active = self.session.active_pokemon
        if not active:
            return

        stat = None
        for s in STATS:
            if active.remaining_evs(s) > 0:
                stat = s
                break

        if not stat:
            _show_message("Complete", f"{active.name} has reached all EV targets!")
            return

        self.session.record_ko({stat: 1})
        self._save_session()
        self._refresh_training_view(view)

    def _show_species_picker(self, training_view):
        v = ui.View(name="Pick Species", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        search = ui.TextField(
            frame=(PAD, y, cw, 32),
            placeholder="Search species...",
        )
        v.add_subview(search)
        y += 40

        tv = ui.TableView(frame=(PAD, y, cw, 350), flex="WH")
        v.add_subview(tv)
        v.table_view = tv
        v.training_view = training_view

        species_evs = self.ev_data.get("species_evs", {})

        def update_list(text):
            q = (text or "").strip().upper()
            matches = []
            for sp, evs in species_evs.items():
                if q and q not in sp:
                    continue
                ev_str = ", ".join(f"+{v} {k}" for k, v in evs.items() if v > 0)
                matches.append({
                    "title": f"{sp.title()}\n{ev_str}",
                    "species": sp,
                    "evs": evs,
                })
                if len(matches) >= 30:
                    break

            ds = ui.ListDataSource(matches if matches else [{"title": "No matches"}])

            def on_select(sender):
                idx = sender.selected_row
                if 0 <= idx < len(matches):
                    evs = matches[idx]["evs"]
                    self.session.record_ko(evs)
                    self._save_session()
                    self._refresh_training_view(v.training_view)
                    self.nav.pop_view()

            ds.action = on_select
            tv.data_source = tv.delegate = ds
            tv.reload()

        class SearchDelegate:
            def textfield_did_change(self, tf):
                update_list(tf.text)

            def textfield_should_return(self, tf):
                tf.end_editing()
                return True

        search.delegate = SearchDelegate()
        update_list("")
        self.nav.push_view(v)

    def _show_vitamin_picker(self, training_view):
        if not self.session.party.can_afford_vitamin():
            _show_message("Not Enough Money", f"Vitamins cost ¥{VITAMIN_PRICE:,}")
            return

        active = self.session.active_pokemon
        if not active:
            return

        v = ui.View(name="Use Vitamin", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        items = []
        for stat in STATS:
            current = active.current_evs.get(stat, 0)
            usable = active.vitamins_usable(stat)
            if usable > 0:
                items.append({
                    "title": f"{stat}: +{VITAMIN_EV} EVs\nCurrent: {current}, Can use: {usable}",
                    "stat": stat,
                })

        if not items:
            _show_message("Cannot Use", "No stats below vitamin cap (100 EVs)")
            return

        tv = ui.TableView(frame=(PAD, y, cw, 300), flex="WH")
        ds = ui.ListDataSource(items)

        def on_select(sender):
            idx = sender.selected_row
            if 0 <= idx < len(items):
                stat = items[idx]["stat"]
                mon_idx = self.session.active_index
                if self.session.party.buy_vitamin(mon_idx, stat):
                    self._save_session()
                    self._refresh_training_view(training_view)
                    self.nav.pop_view()

        ds.action = on_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)
        self.nav.push_view(v)

    def _show_active_picker(self, training_view):
        v = ui.View(name="Switch Pokémon", background_color="white")
        sw = _screen_width()
        cw = _content_width()

        items = []
        for i, mon in enumerate(self.session.party.pokemon):
            remaining = mon.total_remaining()
            current = "→ " if i == self.session.active_index else ""
            items.append({
                "title": f"{current}{mon.name}\n{remaining} EVs remaining",
                "index": i,
            })

        tv = ui.TableView(frame=(PAD, PAD + 50, cw, 300), flex="WH")
        ds = ui.ListDataSource(items)

        def on_select(sender):
            idx = sender.selected_row
            if 0 <= idx < len(items):
                self.session.active_index = items[idx]["index"]
                self._save_session()
                self._refresh_training_view(training_view)
                self.nav.pop_view()

        ds.action = on_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)
        self.nav.push_view(v)

    def _refresh_training_view(self, view):
        active = self.session.active_pokemon
        if hasattr(view, "name_label"):
            view.name_label.text = active.name if active else "None"
        if hasattr(view, "ev_text"):
            view.ev_text.text = format_ev_summary(active) if active else ""
        if hasattr(view, "money_label"):
            view.money_label.text = f"¥{self.session.party.money:,}"

    def _show_settings(self, sender):
        v = ui.View(name="Settings", background_color="white")
        sw = _screen_width()
        cw = _content_width()
        y = PAD + 50

        ver_lbl = ui.Label(frame=(PAD, y, cw, 24), text="Version:", font=("<system>", 14))
        v.add_subview(ver_lbl)
        y += 28
        ver_toggle = _make_toggle(["FireRed", "LeafGreen"], 0 if self.version == "firered" else 1, self._on_version_toggle, y)
        v.add_subview(ver_toggle)
        y += BTN_H + 20

        coin_lbl = ui.Label(frame=(PAD, y, cw - 60, 24), text="Amulet Coin (2× money):", font=("<system>", 14))
        v.add_subview(coin_lbl)
        coin_switch = ui.Switch(frame=(cw - 50, y - 4, 60, 30))
        coin_switch.value = self.session.party.amulet_coin_holder
        coin_switch.action = self._on_amulet_toggle
        v.add_subview(coin_switch)
        y += 40

        money_lbl = ui.Label(frame=(PAD, y, 100, 24), text="Set Money:", font=("<system>", 14))
        v.add_subview(money_lbl)
        money_field = ui.TextField(
            frame=(110, y - 4, cw - 110, 32),
            keyboard_type=ui.KEYBOARD_NUMBER_PAD,
        )
        money_field.text = str(self.session.party.money)
        v.add_subview(money_field)
        v.money_field = money_field
        y += 50

        save_money_btn = ui.Button(
            title="Update Money",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
            action=lambda s: self._update_money(v),
        )
        save_money_btn.tint_color = "#007AFF"
        v.add_subview(save_money_btn)
        y += BTN_H + 20

        reset_btn = ui.Button(
            title="Reset Session",
            frame=(PAD, y, cw, BTN_H),
            font=("<system>", 14),
            action=self._reset_session,
        )
        reset_btn.tint_color = "#FF3B30"
        reset_btn.border_width = 1
        reset_btn.border_color = "#FF3B30"
        reset_btn.corner_radius = 6
        v.add_subview(reset_btn)
        y += BTN_H + 20

        export_btn = ui.Button(
            title="Export Session",
            frame=(PAD, y, cw // 2 - 5, BTN_H),
            font=("<system>", 14),
            action=self._export_session,
        )
        export_btn.tint_color = "#5856D6"
        v.add_subview(export_btn)

        import_btn = ui.Button(
            title="Import Session",
            frame=(PAD + cw // 2 + 5, y, cw // 2 - 5, BTN_H),
            font=("<system>", 14),
            action=self._import_session,
        )
        import_btn.tint_color = "#5856D6"
        v.add_subview(import_btn)

        self.nav.push_view(v)

    def _on_version_toggle(self, sender):
        idx = int(sender.name.split("_")[1])
        parent = sender.superview.superview
        for child in parent.subviews:
            if hasattr(child, "paint"):
                child.paint(idx)
        self.version = "firered" if idx == 0 else "leafgreen"

    def _on_amulet_toggle(self, sender):
        self.session.party.amulet_coin_holder = sender.value
        self._save_session()

    def _update_money(self, view):
        try:
            amount = int(view.money_field.text or "0")
            self.session.party.money = max(0, amount)
            self._save_session()
            self._refresh_main_menu()
        except ValueError:
            pass

    def _reset_session(self, sender):
        self.session = Session()
        self._save_session()
        self.nav.pop_view()
        _show_message("Reset", "Session has been reset")

    def _export_session(self, sender):
        data = json.dumps(self.session.to_dict(), indent=2)
        _show_message("Export Data", f"Copy this JSON:\n\n{data}")

    def _import_session(self, sender):
        _show_message("Import", "Paste JSON into ev_session.json file\nand restart the app.")


def main():
    _console("Starting EV Trainer GUI")
    if ui is None:
        print("EV Trainer GUI requires Pythonista.")
        print("Run ev_trainer.py for CLI usage.")
        return

    try:
        app = EVTrainerApp()
        app.run()
    except Exception:
        _show_message("Error", traceback.format_exc())


if __name__ == "__main__":
    main()
