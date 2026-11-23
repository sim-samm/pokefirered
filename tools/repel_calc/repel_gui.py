#!/usr/bin/env python3
"""
Pythonista GUI for the FR/LG Repel + nature/ability calculator.

Requires Pythonista's ui module. Keep beside:
  repel_filter.py, encounters.json, species_abilities.json

Screens (portrait, tap-first):
  1) Species — search-first (no full dump on load)
  2) Areas — sort Best rate / Natural; shows if Repel helps
  3) Nature / ability — live combined odds

Desktop without ui: message only (use repel_filter.py).
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import repel_filter as rf

try:
    import ui  # type: ignore
except ImportError:
    ui = None


METHOD = "land"
PAD = 8
BTN_H = 36
MIN_SEARCH_CHARS = 1
MAX_SPECIES_RESULTS = 40

# Filled by _install_views() when ui is available.
_SpeciesView = None
_AreasView = None
_HuntView = None
_ErrorView = None


def _all_species(data, version):
    names = set()
    for area in data["areas"]:
        block = rf.area_block(area, version)
        if not block or METHOD not in block:
            continue
        for sp, _, _ in block[METHOD]:
            names.add(rf.normalize_species(sp).replace("_", " ").title())
    return sorted(names)


def _area_rows(data, version, species):
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


def _odds_text(species_pct, best_lead, uses_repel, natures, ability_label, ability_pct):
    nature_pct = 100.0 * len(natures) / len(rf.NATURES)
    p = (species_pct / 100.0) * (nature_pct / 100.0) * (ability_pct / 100.0)
    lead_bit = "no Repel" if not uses_repel else "lead Lv%s" % best_lead
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
            lines.append("  %s: %s" % (label, rf.encounters_for_chance(p, q)))
    else:
        lines.append("Impossible combo")
    return "\n".join(lines)


def _species_key(name):
    key = rf.normalize_species(name)
    if key.startswith("SPECIES_"):
        return key[len("SPECIES_") :]
    return key


def _install_views():
    """Subclass ui.View so layout() is called with no args (Pythonista rule)."""
    global _SpeciesView, _AreasView, _HuntView, _ErrorView

    class SpeciesView(ui.View):
        def __init__(self, app):
            ui.View.__init__(self)
            self.app = app
            self.name = "Species"
            self.background_color = "white"
            self.flex = "WH"

            self.seg = ui.SegmentedControl()
            self.seg.segments = ["FireRed", "LeafGreen"]
            self.seg.selected_index = 0
            self.seg.action = app._on_version
            self.add_subview(self.seg)

            self.field = ui.TextField()
            self.field.placeholder = "Type a species name…"
            self.field.clear_button_mode = "while_editing"
            self.field.autocorrection_type = False
            try:
                self.field.autocapitalization_type = ui.AUTOCAPITALIZE_NONE
            except Exception:
                pass
            self.field.delegate = app
            self.add_subview(self.field)

            self.hint = ui.Label()
            self.hint.number_of_lines = 2
            self.hint.font = ("<system>", 13)
            self.hint.text_color = "#666666"
            self.hint.text = (
                "Type to search (e.g. Growlithe).\nNo full list is loaded up front."
            )
            self.add_subview(self.hint)

            self.tv = ui.TableView()
            self.tv.row_height = 44
            self.tv.flex = "WH"
            ds = ui.ListDataSource([])
            ds.action = app._on_species_select
            self.tv.data_source = self.tv.delegate = ds
            self.add_subview(self.tv)

        def layout(self):
            w = self.width
            y = PAD
            self.seg.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + PAD
            self.field.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + 6
            self.hint.frame = (PAD, y, w - 2 * PAD, 40)
            y += 44
            self.tv.frame = (0, y, w, max(0, self.height - y))

    class AreasView(ui.View):
        def __init__(self, app, title):
            ui.View.__init__(self)
            self.app = app
            self.name = title
            self.background_color = "white"
            self.flex = "WH"

            self.hint = ui.Label()
            self.hint.number_of_lines = 2
            self.hint.font = ("<system>", 12)
            self.hint.text_color = "#666666"
            self.hint.text = "Best = highest of_enc\n(with or without Repel)"
            self.add_subview(self.hint)

            self.seg = ui.SegmentedControl()
            self.seg.segments = ["Best rate", "Natural"]
            self.seg.selected_index = 0 if app.sort_mode == "best" else 1
            self.seg.action = app._on_sort
            self.add_subview(self.seg)

            self.tv = ui.TableView()
            self.tv.row_height = 60
            self.tv.flex = "WH"
            ds = ui.ListDataSource([])
            ds.action = app._on_area_select
            self.tv.data_source = self.tv.delegate = ds
            self.add_subview(self.tv)

        def layout(self):
            w = self.width
            y = PAD
            self.hint.frame = (PAD, y, w - 2 * PAD, 36)
            y += 40
            self.seg.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + PAD
            self.tv.frame = (0, y, w, max(0, self.height - y))

    class HuntView(ui.View):
        def __init__(self, app, title):
            ui.View.__init__(self)
            self.app = app
            self.name = title
            self.background_color = "white"
            self.flex = "WH"

            self.scroll = ui.ScrollView()
            self.scroll.background_color = "white"
            self.add_subview(self.scroll)

            self.content = ui.View()
            self.content.background_color = "white"
            self.scroll.add_subview(self.content)

            self.plus_hdr = ui.Label()
            self.plus_hdr.text = "Nice as +"
            self.plus_hdr.font = ("<system-bold>", 14)
            self.content.add_subview(self.plus_hdr)

            self.plus_row = ui.View()
            self.content.add_subview(self.plus_row)
            app._build_stat_row(self.plus_row, "plus")

            self.minus_hdr = ui.Label()
            self.minus_hdr.text = "Nice as −"
            self.minus_hdr.font = ("<system-bold>", 14)
            self.content.add_subview(self.minus_hdr)

            self.minus_row = ui.View()
            self.content.add_subview(self.minus_row)
            app._build_stat_row(self.minus_row, "minus")

            self.neut = ui.Switch()
            self.neut.value = app.include_neutral
            self.neut.action = app._on_neutral
            self.content.add_subview(self.neut)

            self.neut_lab = ui.Label()
            self.neut_lab.text = "Include neutrals"
            self.neut_lab.font = ("<system>", 14)
            self.content.add_subview(self.neut_lab)

            self.natures_lab = ui.Label()
            self.natures_lab.number_of_lines = 0
            self.natures_lab.font = ("<system>", 13)
            self.content.add_subview(self.natures_lab)

            self.abil_hdr = ui.Label()
            self.abil_hdr.text = "Ability"
            self.abil_hdr.font = ("<system-bold>", 14)
            self.content.add_subview(self.abil_hdr)

            self.abil_seg = ui.SegmentedControl()
            self.abil_seg.action = app._on_ability
            self.content.add_subview(self.abil_seg)

            self.odds_lab = ui.Label()
            self.odds_lab.number_of_lines = 0
            self.odds_lab.font = ("<system>", 14)
            self.content.add_subview(self.odds_lab)

        def layout(self):
            w = max(self.width, 1)
            h = max(self.height, 1)
            self.scroll.frame = (0, 0, w, h)
            pw = w - 2 * PAD
            y = PAD
            self.plus_hdr.frame = (PAD, y, pw, 20)
            y += 24
            self.plus_row.frame = (PAD, y, pw, BTN_H)
            self.app._layout_stat_row(self.plus_row)
            y += BTN_H + 14
            self.minus_hdr.frame = (PAD, y, pw, 20)
            y += 24
            self.minus_row.frame = (PAD, y, pw, BTN_H)
            self.app._layout_stat_row(self.minus_row)
            y += BTN_H + 14
            self.neut.frame = (PAD, y, 51, 31)
            self.neut_lab.frame = (PAD + 58, y, pw - 58, 31)
            y += 40
            try:
                self.natures_lab.size_to_fit()
            except Exception:
                pass
            nh = max(80, min(220, getattr(self.natures_lab, "height", 80) or 80))
            self.natures_lab.frame = (PAD, y, pw, nh)
            y += nh + 12
            self.abil_hdr.frame = (PAD, y, pw, 20)
            y += 24
            self.abil_seg.frame = (PAD, y, pw, BTN_H)
            y += BTN_H + 14
            try:
                self.odds_lab.size_to_fit()
            except Exception:
                pass
            oh = max(160, getattr(self.odds_lab, "height", 160) or 160)
            self.odds_lab.frame = (PAD, y, pw, oh)
            y += oh + 40
            self.content.frame = (0, 0, w, max(h + 1, y))
            self.scroll.content_size = (w, self.content.height)

    class ErrorView(ui.View):
        def __init__(self, message):
            ui.View.__init__(self)
            self.name = "Error"
            self.background_color = "white"
            self.flex = "WH"
            self.lab = ui.Label()
            self.lab.text = message
            self.lab.number_of_lines = 0
            self.lab.font = ("<system>", 14)
            self.add_subview(self.lab)

        def layout(self):
            self.lab.frame = (PAD, PAD, self.width - 2 * PAD, self.height - 2 * PAD)

    _SpeciesView = SpeciesView
    _AreasView = AreasView
    _HuntView = HuntView
    _ErrorView = ErrorView


class RepelApp:
    def __init__(self):
        self.data = None
        self.abilities = {"species": {}}
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
        self._hunt_view = None
        self._area_view = None

        _install_views()

        try:
            self.data = rf.load_data()
            self.abilities = rf.load_abilities()
        except SystemExit as e:
            msg = str(e) or "Missing encounters.json next to this script."
            self.root = _ErrorView(msg)
            self.nav = ui.NavigationView(self.root)
            return
        except Exception:
            self.root = _ErrorView(traceback.format_exc())
            self.nav = ui.NavigationView(self.root)
            return

        self.root = _SpeciesView(self)
        self.nav = ui.NavigationView(self.root)

    def present(self):
        self.nav.present("fullscreen")

    # ----- Species (search-first) -----
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
            # Built once per version, only after the user types.
            self._species_cache[self.version] = _all_species(self.data, self.version)
        return self._species_cache[self.version]

    def _reload_species_list(self):
        if _SpeciesView is None or not isinstance(self.root, _SpeciesView):
            return
        field = self.root.field
        tv = self.root.tv
        hint = self.root.hint
        q = (field.text or "").strip().lower()
        if len(q) < MIN_SEARCH_CHARS:
            tv.data_source.items = []
            tv.reload()
            hint.text = (
                "Type to search (e.g. Growlithe).\nNo full list is loaded up front."
            )
            return
        matches = []
        for name in self._species_names():
            if q in name.lower():
                matches.append(name)
            if len(matches) >= MAX_SPECIES_RESULTS:
                break
        items = [
            {"title": name, "accessory_type": "disclosure_indicator"} for name in matches
        ]
        tv.data_source.items = items
        tv.reload()
        if not matches:
            hint.text = 'No match for "%s".' % q
        elif len(matches) >= MAX_SPECIES_RESULTS:
            hint.text = "Showing first %d — type more to narrow." % MAX_SPECIES_RESULTS
        else:
            hint.text = "%d match%s" % (len(matches), "" if len(matches) == 1 else "es")

    def _on_species_select(self, sender):
        if sender.selected_row < 0:
            return
        self.species = sender.items[sender.selected_row]["title"]
        try:
            self.root.field.end_editing()
        except Exception:
            pass
        self.nav.push_view(self._make_areas_view())

    # ----- Areas -----
    def _make_areas_view(self):
        v = _AreasView(self, self.species)
        self._area_view = v
        self._reload_areas()
        return v

    def _on_sort(self, sender):
        self.sort_mode = "best" if sender.selected_index == 0 else "natural"
        self._reload_areas()

    def _reload_areas(self):
        rows = _sort_rows(
            _area_rows(self.data, self.version, self.species), self.sort_mode
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
        tv = self._area_view.tv
        tv.data_source.items = items
        tv.reload()

    def _on_area_select(self, sender):
        if sender.selected_row < 0:
            return
        self.area_row = self._area_rows_cache[sender.selected_row]
        self.plus = set()
        self.minus = set()
        self.include_neutral = True
        self.ability_choice = "either"
        self.nav.push_view(self._make_hunt_view())

    # ----- Nature / ability -----
    def _make_hunt_view(self):
        v = _HuntView(self, self.area_row["title"])
        self._hunt_view = v
        self._setup_ability_segments()
        self._refresh_hunt()
        return v

    def _build_stat_row(self, row, which):
        for i, key in enumerate(rf.STAT_KEYS):
            b = ui.Button(title=key)
            b.name = "%s_%d" % (which, i)
            b.font = ("<system>", 13)
            b.border_width = 1
            b.border_color = "#CCCCCC"
            b.corner_radius = 6
            b.action = self._on_stat
            row.add_subview(b)
        self._paint_stat_row(row, which)

    def _layout_stat_row(self, row):
        n = len(rf.STAT_KEYS)
        gap = 4
        bw = (row.width - gap * (n - 1)) / max(n, 1)
        for i, b in enumerate(row.subviews):
            b.frame = (i * (bw + gap), 0, bw, BTN_H)

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
        meta = self.abilities.get("species", {}).get(_species_key(self.species))
        seg = self._hunt_view.abil_seg
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
        meta = self.abilities.get("species", {}).get(_species_key(self.species)) or {}
        if not meta.get("dual"):
            self.ability_choice = "0"
        else:
            self.ability_choice = {0: "0", 1: "1", 2: "either"}.get(
                sender.selected_index, "either"
            )
        self._refresh_hunt()

    def _current_natures(self):
        if not self.plus and not self.minus:
            return list(rf.NATURES)
        return rf.nature_matches(self.plus, self.minus, self.include_neutral)

    def _current_ability(self):
        meta = self.abilities.get("species", {}).get(_species_key(self.species))
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
        if not self._hunt_view or not self.area_row:
            return
        summary = self.area_row["summary"]
        natures = self._current_natures()
        without = rf.nature_matches(self.plus, self.minus, False)
        recommend = len(without) < 5 or summary.best_pct < 15.0
        self._hunt_view.neut_lab.text = (
            "Include neutrals (recommended)" if recommend else "Include neutrals"
        )

        nat_lines = ["Natures %d/25" % len(natures)]
        for name, up, down in natures[:10]:
            nat_lines.append(rf.format_nature_line(name, up, down))
        if len(natures) > 10:
            nat_lines.append("… +%d more" % (len(natures) - 10))
        self._hunt_view.natures_lab.text = "\n".join(nat_lines)

        abil_label, abil_pct = self._current_ability()
        self._hunt_view.odds_lab.text = _odds_text(
            summary.best_pct,
            summary.best_lead,
            summary.uses_repel,
            natures,
            abil_label,
            abil_pct,
        )
        try:
            self._hunt_view.natures_lab.size_to_fit()
            self._hunt_view.odds_lab.size_to_fit()
            self._hunt_view.set_needs_layout()
        except Exception:
            pass


def main():
    if ui is None:
        print("repel_gui.py needs Pythonista's ui module.")
        print("On desktop use: python3 repel_filter.py")
        return 1
    try:
        RepelApp().present()
    except Exception:
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
