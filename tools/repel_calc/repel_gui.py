#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pythonista tap GUI for the FR/LG Repel calculator.

Keep beside: repel_filter.py, encounters.json, species_abilities.json
Run this file in Pythonista. Text UI remains: repel_filter.py

Notes for Pythonista stability:
- No custom ui.View subclasses (plain View + flex only).
- Do not raise SystemExit after presenting a view (that looks like a crash).
- Import/load errors are shown on screen; also printed to the console.
"""

import sys
import traceback

try:
    import ui  # type: ignore
except ImportError:
    ui = None


METHOD = "land"
PAD = 8
BTN_H = 36
MIN_SEARCH_CHARS = 1
MAX_SPECIES_RESULTS = 40


def _console(msg):
    print("[repel_gui] " + str(msg))


def _show_message(title, message):
    """Present a simple full-screen message. Never SystemExit after this."""
    _console(title + ": " + message[:200])
    if ui is None:
        print(message)
        return
    v = ui.View(name=title)
    v.background_color = "white"
    lab = ui.Label(frame=(PAD, PAD, 300, 500), flex="WH")
    lab.number_of_lines = 0
    lab.font = ("<system>", 13)
    lab.text = message
    v.add_subview(lab)
    # Prefer plain present — NavigationView not required for errors.
    v.present("fullscreen")


def _species_key(rf, name):
    key = rf.normalize_species(name)
    if key.startswith("SPECIES_"):
        return key[len("SPECIES_") :]
    return key


def _all_species(rf, data, version):
    names = set()
    for area in data["areas"]:
        block = rf.area_block(area, version)
        if not block or METHOD not in block:
            continue
        for sp, _, _ in block[METHOD]:
            names.add(rf.normalize_species(sp).replace("_", " ").title())
    return sorted(names)


def _area_rows(rf, data, version, species):
    rows = []
    for area, block in rf.find_areas(data, version, species=species, method=METHOD):
        slots = rf.slots_from_block(block, METHOD, data["slot_rates"])
        summary = rf.summarize_area_rates(slots, species)
        if summary is None:
            continue
        rows.append(
            {
                "area": area,
                "slots": slots,
                "summary": summary,
                "title": rf.friendly_map_name(area["id"], area.get("name")),
                "id": area["id"],
            }
        )
    return rows


def _sort_rows(rows, mode):
    if mode == "natural":
        return sorted(rows, key=lambda r: (-r["summary"].natural_pct, r["id"]))
    return sorted(rows, key=lambda r: (-r["summary"].best_pct, r["id"]))


def _odds_text(rf, species_pct, best_lead, uses_repel, natures, ability_label, ability_pct):
    nature_pct = 100.0 * len(natures) / len(rf.NATURES)
    p = (species_pct / 100.0) * (nature_pct / 100.0) * (ability_pct / 100.0)
    lead_bit = "no Repel" if not uses_repel else ("lead Lv%s" % best_lead)
    lines = [
        "Species %s" % rf._pct(species_pct),
        "  (%s)" % lead_bit,
        "Nature %s (%d/25)" % (rf._pct(nature_pct), len(natures)),
        "Ability %s" % ability_label,
        "  %s" % rf._pct(ability_pct),
        "",
        "Combined %s" % rf._pct(p * 100.0, 4),
    ]
    if p > 0:
        lines.append("1 in %.1f enc" % (1.0 / p))
        lines.append("Seen by:")
        for label, q in (("50%", 0.50), ("75%", 0.75), ("90%", 0.90), ("95%", 0.95)):
            lines.append(
                "  %s: %s" % (label, rf.encounters_for_chance(p, q))
            )
    else:
        lines.append("Impossible combo")
    return "\n".join(lines)


class RepelApp(object):
    def __init__(self, rf, data, abilities):
        self.rf = rf
        self.data = data
        self.abilities = abilities
        self.version = "firered"
        self.species = None
        self.area_row = None
        self.sort_mode = "best"
        self.plus = set()
        self.minus = set()
        self.include_neutral = True
        self.ability_choice = "either"
        self._area_rows_cache = []
        self._species_cache = {}
        self._area_tv = None
        self._hunt = {}
        self._species_view = None

        root = self._make_species_view()
        self.nav = ui.NavigationView(root)

    def present(self):
        self.nav.present("fullscreen")

    def _make_species_view(self):
        v = ui.View(name="Species")
        v.background_color = "white"

        seg = ui.SegmentedControl(
            frame=(PAD, PAD, 304, BTN_H),
            flex="W",
            segments=["FireRed", "LeafGreen"],
            selected_index=0,
            action=self._on_version,
        )
        v.add_subview(seg)

        field = ui.TextField(
            frame=(PAD, PAD + BTN_H + 8, 304, BTN_H),
            flex="W",
            placeholder="Type a species name",
            clear_button_mode="while_editing",
            autocorrection_type=False,
            delegate=self,
        )
        field.name = "search"
        v.add_subview(field)

        hint = ui.Label(
            frame=(PAD, PAD + 2 * (BTN_H + 8), 304, 40),
            flex="W",
            number_of_lines=2,
            font=("<system>", 13),
            text_color="#666666",
            text="Type to search (e.g. Growlithe).",
        )
        hint.name = "hint"
        v.add_subview(hint)

        tv = ui.TableView(
            frame=(0, 140, 320, 400),
            flex="WH",
            row_height=44,
        )
        tv.name = "species_table"
        ds = ui.ListDataSource([])
        ds.action = self._on_species_select
        tv.data_source = ds
        tv.delegate = ds
        v.add_subview(tv)

        self._species_view = v
        return v

    def textfield_did_change(self, textfield):
        self._reload_species_list()

    def textfield_should_return(self, textfield):
        textfield.end_editing()
        return True

    def _on_version(self, sender):
        self.version = "firered" if sender.selected_index == 0 else "leafgreen"
        self._reload_species_list()

    def _species_names(self):
        if self.version not in self._species_cache:
            _console("building species index for " + self.version)
            self._species_cache[self.version] = _all_species(
                self.rf, self.data, self.version
            )
        return self._species_cache[self.version]

    def _reload_species_list(self):
        v = self._species_view
        field = v["search"]
        tv = v["species_table"]
        hint = v["hint"]
        q = (field.text or "").strip().lower()
        if len(q) < MIN_SEARCH_CHARS:
            tv.data_source.items = []
            tv.reload()
            hint.text = "Type to search (e.g. Growlithe)."
            return
        matches = []
        for name in self._species_names():
            if q in name.lower():
                matches.append(name)
            if len(matches) >= MAX_SPECIES_RESULTS:
                break
        items = []
        for name in matches:
            items.append(
                {"title": name, "accessory_type": "disclosure_indicator"}
            )
        tv.data_source.items = items
        tv.reload()
        if not matches:
            hint.text = 'No match for "%s".' % q
        elif len(matches) >= MAX_SPECIES_RESULTS:
            hint.text = "Showing first %d — type more to narrow." % MAX_SPECIES_RESULTS
        else:
            hint.text = "%d match%s" % (
                len(matches),
                "" if len(matches) == 1 else "es",
            )

    def _on_species_select(self, sender):
        if sender.selected_row < 0:
            return
        self.species = sender.items[sender.selected_row]["title"]
        try:
            self._species_view["search"].end_editing()
        except Exception:
            pass
        try:
            self.nav.push_view(self._make_areas_view())
        except Exception:
            _show_message("Error", traceback.format_exc())

    def _make_areas_view(self):
        v = ui.View(name=self.species)
        v.background_color = "white"

        hint = ui.Label(
            frame=(PAD, PAD, 304, 36),
            flex="W",
            number_of_lines=2,
            font=("<system>", 12),
            text_color="#666666",
            text="Best = highest of_enc (with or without Repel)",
        )
        v.add_subview(hint)

        seg = ui.SegmentedControl(
            frame=(PAD, PAD + 40, 304, BTN_H),
            flex="W",
            segments=["Best rate", "Natural"],
            selected_index=0 if self.sort_mode == "best" else 1,
            action=self._on_sort,
        )
        v.add_subview(seg)

        tv = ui.TableView(
            frame=(0, PAD + 40 + BTN_H + 8, 320, 400),
            flex="WH",
            row_height=60,
        )
        ds = ui.ListDataSource([])
        ds.action = self._on_area_select
        tv.data_source = ds
        tv.delegate = ds
        v.add_subview(tv)

        self._area_tv = tv
        self._reload_areas()
        return v

    def _on_sort(self, sender):
        self.sort_mode = "best" if sender.selected_index == 0 else "natural"
        self._reload_areas()

    def _reload_areas(self):
        rf = self.rf
        rows = _sort_rows(
            _area_rows(rf, self.data, self.version, self.species), self.sort_mode
        )
        self._area_rows_cache = rows
        items = []
        for r in rows:
            s = r["summary"]
            if self.sort_mode == "best":
                detail = "%s · %s" % (rf._pct(s.best_pct), s.lead_label)
                extra = "natural %s" % rf._pct(s.natural_pct)
            else:
                detail = "%s · no Repel" % rf._pct(s.natural_pct)
                extra = "best %s (%s)" % (rf._pct(s.best_pct), s.lead_label)
            items.append(
                {
                    "title": "%s\n%s · %s" % (r["title"], detail, extra),
                    "accessory_type": "disclosure_indicator",
                }
            )
        self._area_tv.data_source.items = items
        self._area_tv.reload()

    def _on_area_select(self, sender):
        if sender.selected_row < 0:
            return
        self.area_row = self._area_rows_cache[sender.selected_row]
        self.plus = set()
        self.minus = set()
        self.include_neutral = True
        self.ability_choice = "either"
        try:
            self.nav.push_view(self._make_hunt_view())
        except Exception:
            _show_message("Error", traceback.format_exc())

    def _make_hunt_view(self):
        row = self.area_row
        v = ui.View(name=row["title"])
        v.background_color = "white"

        scroll = ui.ScrollView(
            frame=(0, 0, 320, 500),
            flex="WH",
            background_color="white",
        )
        v.add_subview(scroll)

        content = ui.View(frame=(0, 0, 320, 900), background_color="white")
        scroll.add_subview(content)

        y = PAD
        w = 304

        def add_label(text, bold=False, height=22):
            nonlocal y
            lab = ui.Label(
                frame=(PAD, y, w, height),
                flex="W",
                text=text,
                font=("<system-bold>", 14) if bold else ("<system>", 14),
            )
            content.add_subview(lab)
            y += height + 6
            return lab

        add_label("Nice as +", bold=True)
        plus_row = ui.View(frame=(PAD, y, w, BTN_H), flex="W")
        content.add_subview(plus_row)
        self._build_stat_row(plus_row, "plus")
        y += BTN_H + 12

        add_label("Nice as -", bold=True)
        minus_row = ui.View(frame=(PAD, y, w, BTN_H), flex="W")
        content.add_subview(minus_row)
        self._build_stat_row(minus_row, "minus")
        y += BTN_H + 12

        neut = ui.Switch(frame=(PAD, y, 51, 31), value=self.include_neutral)
        neut.action = self._on_neutral
        content.add_subview(neut)

        neut_lab = ui.Label(
            frame=(PAD + 58, y, w - 58, 31),
            flex="W",
            text="Include neutrals",
            font=("<system>", 14),
        )
        content.add_subview(neut_lab)
        y += 40

        natures_lab = ui.Label(
            frame=(PAD, y, w, 160),
            flex="W",
            number_of_lines=0,
            font=("<system>", 13),
        )
        content.add_subview(natures_lab)
        y += 168

        add_label("Ability", bold=True)
        abil = ui.SegmentedControl(frame=(PAD, y, w, BTN_H), flex="W")
        abil.action = self._on_ability
        content.add_subview(abil)
        y += BTN_H + 12

        odds_lab = ui.Label(
            frame=(PAD, y, w, 220),
            flex="W",
            number_of_lines=0,
            font=("<system>", 14),
        )
        content.add_subview(odds_lab)
        y += 240

        content.height = y + 40
        scroll.content_size = (320, content.height)

        self._hunt = {
            "neut_lab": neut_lab,
            "natures_lab": natures_lab,
            "abil_seg": abil,
            "odds_lab": odds_lab,
        }
        self._setup_ability_segments()
        self._refresh_hunt()
        return v

    def _build_stat_row(self, row, which):
        n = len(self.rf.STAT_KEYS)
        total_w = 304
        gap = 4
        bw = (total_w - gap * (n - 1)) / float(n)
        for i, key in enumerate(self.rf.STAT_KEYS):
            b = ui.Button(
                title=key,
                frame=(i * (bw + gap), 0, bw, BTN_H),
                font=("<system>", 13),
                border_width=1,
                border_color="#CCCCCC",
                corner_radius=6,
                action=self._on_stat,
            )
            b.name = "%s_%d" % (which, i)
            row.add_subview(b)
        self._paint_stat_row(row, which)

    def _paint_stat_row(self, row, which):
        selected = self.plus if which == "plus" else self.minus
        for b in row.subviews:
            idx = int(b.name.split("_")[1])
            on = idx in selected
            b.background_color = "#007AFF" if on else "#F2F2F7"
            b.tint_color = "white" if on else "#111111"

    def _on_stat(self, sender):
        which, idx_s = sender.name.split("_")
        idx = int(idx_s)
        bucket = self.plus if which == "plus" else self.minus
        if idx in bucket:
            bucket.discard(idx)
        else:
            bucket.add(idx)
        self._paint_stat_row(sender.superview, which)
        self._refresh_hunt()

    def _on_neutral(self, sender):
        self.include_neutral = bool(sender.value)
        self._refresh_hunt()

    def _setup_ability_segments(self):
        meta = self.abilities.get("species", {}).get(
            _species_key(self.rf, self.species)
        )
        seg = self._hunt["abil_seg"]
        if not meta:
            seg.segments = ["Either"]
            seg.selected_index = 0
            seg.enabled = False
            self.ability_choice = "either"
            return
        if not meta.get("dual"):
            seg.segments = [meta["slot0"]]
            seg.selected_index = 0
            seg.enabled = False
            self.ability_choice = "0"
            return
        seg.enabled = True
        seg.segments = [meta["slot0"], meta["slot1"], "Either"]
        seg.selected_index = 2
        self.ability_choice = "either"

    def _on_ability(self, sender):
        meta = self.abilities.get("species", {}).get(
            _species_key(self.rf, self.species)
        ) or {}
        if not meta.get("dual"):
            self.ability_choice = "0"
        else:
            mapping = {0: "0", 1: "1", 2: "either"}
            self.ability_choice = mapping.get(sender.selected_index, "either")
        self._refresh_hunt()

    def _current_natures(self):
        if not self.plus and not self.minus:
            return list(self.rf.NATURES)
        return self.rf.nature_matches(self.plus, self.minus, self.include_neutral)

    def _current_ability(self):
        meta = self.abilities.get("species", {}).get(
            _species_key(self.rf, self.species)
        )
        if not meta:
            return "Either", 100.0
        if not meta.get("dual"):
            return meta["slot0"], 100.0
        if self.ability_choice == "0":
            return meta["slot0"], 50.0
        if self.ability_choice == "1":
            return meta["slot1"], 50.0
        return "Either", 100.0

    def _refresh_hunt(self):
        rf = self.rf
        h = self._hunt
        summary = self.area_row["summary"]
        natures = self._current_natures()
        without = rf.nature_matches(self.plus, self.minus, False)
        recommend = len(without) < 5 or summary.best_pct < 15.0
        h["neut_lab"].text = (
            "Include neutrals (recommended)" if recommend else "Include neutrals"
        )

        nat_lines = ["Natures %d/25" % len(natures)]
        for name, up, down in natures[:10]:
            nat_lines.append(rf.format_nature_line(name, up, down))
        if len(natures) > 10:
            nat_lines.append("... +%d more" % (len(natures) - 10))
        h["natures_lab"].text = "\n".join(nat_lines)

        abil_label, abil_pct = self._current_ability()
        h["odds_lab"].text = _odds_text(
            rf,
            summary.best_pct,
            summary.best_lead,
            summary.uses_repel,
            natures,
            abil_label,
            abil_pct,
        )


def _load_backend():
    here = None
    try:
        from pathlib import Path

        here = Path(__file__).resolve().parent
        if str(here) not in sys.path:
            sys.path.insert(0, str(here))
    except Exception as exc:
        _console("path setup: " + repr(exc))

    try:
        import repel_filter as rf
    except Exception:
        raise RuntimeError(
            "Could not import repel_filter.py.\n"
            "Put ALL four files in the SAME Pythonista folder:\n"
            "  repel_gui.py\n"
            "  repel_filter.py\n"
            "  encounters.json\n"
            "  species_abilities.json\n\n"
            + traceback.format_exc()
        )

    try:
        data = rf.load_data()
    except SystemExit as e:
        raise RuntimeError(
            "Missing encounters.json next to this script.\n%s" % e
        )
    except Exception:
        raise RuntimeError(
            "Failed loading encounters.json:\n" + traceback.format_exc()
        )

    try:
        abilities = rf.load_abilities()
    except Exception:
        abilities = {"species": {}}

    return rf, data, abilities


def main():
    _console("start")
    if ui is None:
        print("repel_gui.py needs Pythonista's ui module.")
        print("On desktop use: python3 repel_filter.py")
        return

    try:
        _console("loading data")
        rf, data, abilities = _load_backend()
        _console("areas=%d" % len(data.get("areas", [])))
        _console("building UI")
        app = RepelApp(rf, data, abilities)
        _console("present")
        app.present()
        _console("presented ok")
    except Exception:
        # Show on screen; do NOT SystemExit afterward (Pythonista treats that as a crash).
        _show_message("Error", traceback.format_exc())


if __name__ == "__main__":
    main()
