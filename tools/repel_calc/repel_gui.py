#!/usr/bin/env python3
"""
Pythonista GUI for the FR/LG Repel + nature/ability calculator.

Requires Pythonista's ui module. Keep beside:
  repel_filter.py, encounters.json, species_abilities.json

Screens (portrait, tap-first):
  1) Species (FR/LG + search)
  2) Areas — sort Best rate / Natural; shows if Repel helps
  3) Nature / ability — live combined odds

Desktop without ui: message only (use repel_filter.py).
"""

from __future__ import annotations

import sys
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


def _all_species(data: dict, version: str) -> list[str]:
    names: set[str] = set()
    for area in data["areas"]:
        block = rf.area_block(area, version)
        if not block or METHOD not in block:
            continue
        for sp, _, _ in block[METHOD]:
            names.add(rf.normalize_species(sp).replace("_", " ").title())
    return sorted(names)


def _area_rows(data: dict, version: str, species: str) -> list[dict]:
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


def _sort_rows(rows: list[dict], mode: str) -> list[dict]:
    if mode == "natural":
        return sorted(rows, key=lambda r: (-r["summary"].natural_pct, r["id"]))
    return sorted(rows, key=lambda r: (-r["summary"].best_pct, r["id"]))


def _odds_text(
    species_pct: float,
    best_lead: int | None,
    uses_repel: bool,
    natures: list,
    ability_label: str,
    ability_pct: float,
) -> str:
    nature_pct = 100.0 * len(natures) / len(rf.NATURES)
    p = (species_pct / 100.0) * (nature_pct / 100.0) * (ability_pct / 100.0)
    lead_bit = "no Repel" if not uses_repel else f"lead Lv{best_lead}"
    lines = [
        f"Species {rf._pct(species_pct)}",
        f"  ({lead_bit})",
        f"Nature {rf._pct(nature_pct)} ({len(natures)}/25)",
        f"Ability {ability_label}",
        f"  {rf._pct(ability_pct)}",
        "",
        f"Combined {rf._pct(p * 100.0, 4)}",
    ]
    if p > 0:
        lines.append(f"1 in {1.0 / p:.1f} enc")
        lines.append("Seen by:")
        for label, q in (("50%", 0.50), ("75%", 0.75), ("90%", 0.90), ("95%", 0.95)):
            lines.append(f"  {label}: {rf.encounters_for_chance(p, q)}")
    else:
        lines.append("Impossible combo")
    return "\n".join(lines)


class RepelApp:
    def __init__(self):
        self.data = rf.load_data()
        self.abilities = rf.load_abilities()
        self.version = "firered"
        self.species = None
        self.area_row = None
        self.sort_mode = "best"
        self.plus: set[int] = set()
        self.minus: set[int] = set()
        self.include_neutral = True
        self.ability_choice = "either"
        self._area_rows_cache: list[dict] = []

        self.root = self._make_species_view()
        self.nav = ui.NavigationView(self.root)

    def present(self):
        self.nav.present("fullscreen")

    # ----- Species -----
    def _make_species_view(self) -> "ui.View":
        v = ui.View(name="Species")
        v.background_color = "white"
        v.flex = "WH"

        seg = ui.SegmentedControl()
        seg.name = "version"
        seg.segments = ["FireRed", "LeafGreen"]
        seg.selected_index = 0
        seg.action = self._on_version
        seg.flex = "W"
        v.add_subview(seg)

        field = ui.TextField()
        field.name = "search"
        field.placeholder = "Search species"
        field.clear_button_mode = "while_editing"
        field.autocorrection_type = False
        field.autocapitalization_type = ui.AUTOCAPITALIZE_NONE
        field.delegate = self
        field.flex = "W"
        v.add_subview(field)

        tv = ui.TableView()
        tv.name = "species_table"
        tv.flex = "WH"
        tv.row_height = 44
        ds = ui.ListDataSource([])
        ds.action = self._on_species_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)

        def layout(sender):
            w = sender.width
            y = PAD
            seg.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + PAD
            field.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + PAD
            tv.frame = (0, y, w, max(0, sender.height - y))

        v.layout = layout
        self._species_view = v
        self._reload_species_list()
        return v

    def textfield_did_change(self, textfield):
        self._reload_species_list()

    def _on_version(self, sender):
        self.version = "firered" if sender.selected_index == 0 else "leafgreen"
        self._reload_species_list()

    def _reload_species_list(self):
        field = self._species_view["search"]
        tv = self._species_view["species_table"]
        q = (field.text or "").strip().lower()
        items = []
        for name in _all_species(self.data, self.version):
            if q and q not in name.lower():
                continue
            items.append({"title": name, "accessory_type": "disclosure_indicator"})
        tv.data_source.items = items
        tv.reload()

    def _on_species_select(self, sender):
        if sender.selected_row < 0:
            return
        self.species = sender.items[sender.selected_row]["title"]
        self.nav.push_view(self._make_areas_view())

    # ----- Areas -----
    def _make_areas_view(self) -> "ui.View":
        v = ui.View(name=self.species)
        v.background_color = "white"
        v.flex = "WH"

        hint = ui.Label()
        hint.name = "hint"
        hint.number_of_lines = 2
        hint.font = ("<system>", 12)
        hint.text_color = "#666666"
        hint.text = "Best = highest of_enc\n(with or without Repel)"
        hint.flex = "W"
        v.add_subview(hint)

        seg = ui.SegmentedControl()
        seg.name = "sort"
        seg.segments = ["Best rate", "Natural"]
        seg.selected_index = 0 if self.sort_mode == "best" else 1
        seg.action = self._on_sort
        seg.flex = "W"
        v.add_subview(seg)

        tv = ui.TableView()
        tv.name = "area_table"
        tv.flex = "WH"
        tv.row_height = 60
        ds = ui.ListDataSource([])
        ds.action = self._on_area_select
        tv.data_source = tv.delegate = ds
        v.add_subview(tv)

        def layout(sender):
            w = sender.width
            y = PAD
            hint.frame = (PAD, y, w - 2 * PAD, 36)
            y += 40
            seg.frame = (PAD, y, w - 2 * PAD, BTN_H)
            y += BTN_H + PAD
            tv.frame = (0, y, w, max(0, sender.height - y))

        v.layout = layout
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
                detail = f"{rf._pct(s.best_pct)} · {s.lead_label}"
                extra = f"natural {rf._pct(s.natural_pct)}"
            else:
                detail = f"{rf._pct(s.natural_pct)} · no Repel"
                extra = f"best {rf._pct(s.best_pct)} ({s.lead_label})"
            # Single title string — reliable on Pythonista ListDataSource
            items.append(
                {
                    "title": f"{r['title']}\n{detail} · {extra}",
                    "accessory_type": "disclosure_indicator",
                }
            )
        tv = self._area_view["area_table"]
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
    def _make_hunt_view(self) -> "ui.View":
        row = self.area_row
        v = ui.View(name=row["title"])
        v.background_color = "white"
        v.flex = "WH"

        scroll = ui.ScrollView()
        scroll.background_color = "white"
        v.add_subview(scroll)

        content = ui.View()
        content.background_color = "white"
        scroll.add_subview(content)

        plus_hdr = ui.Label()
        plus_hdr.text = "Nice as +"
        plus_hdr.font = ("<system-bold>", 14)
        content.add_subview(plus_hdr)

        plus_row = ui.View()
        content.add_subview(plus_row)
        self._build_stat_row(plus_row, "plus")

        minus_hdr = ui.Label()
        minus_hdr.text = "Nice as −"
        minus_hdr.font = ("<system-bold>", 14)
        content.add_subview(minus_hdr)

        minus_row = ui.View()
        content.add_subview(minus_row)
        self._build_stat_row(minus_row, "minus")

        neut = ui.Switch()
        neut.value = self.include_neutral
        neut.action = self._on_neutral
        content.add_subview(neut)
        self._neut = neut

        neut_lab = ui.Label()
        neut_lab.text = "Include neutrals"
        neut_lab.font = ("<system>", 14)
        content.add_subview(neut_lab)
        self._neut_lab = neut_lab

        natures = ui.Label()
        natures.number_of_lines = 0
        natures.font = ("<system>", 13)
        content.add_subview(natures)
        self._natures_lab = natures

        abil_hdr = ui.Label()
        abil_hdr.text = "Ability"
        abil_hdr.font = ("<system-bold>", 14)
        content.add_subview(abil_hdr)

        abil = ui.SegmentedControl()
        abil.action = self._on_ability
        content.add_subview(abil)
        self._abil_seg = abil

        odds = ui.Label()
        odds.number_of_lines = 0
        odds.font = ("<system>", 14)
        content.add_subview(odds)
        self._odds_lab = odds

        def layout(sender):
            w = max(sender.width, 1)
            h = max(sender.height, 1)
            scroll.frame = (0, 0, w, h)
            pw = w - 2 * PAD
            y = PAD
            plus_hdr.frame = (PAD, y, pw, 20)
            y += 24
            plus_row.frame = (PAD, y, pw, BTN_H)
            self._layout_stat_row(plus_row)
            y += BTN_H + 14
            minus_hdr.frame = (PAD, y, pw, 20)
            y += 24
            minus_row.frame = (PAD, y, pw, BTN_H)
            self._layout_stat_row(minus_row)
            y += BTN_H + 14
            neut.frame = (PAD, y, 51, 31)
            neut_lab.frame = (PAD + 58, y, pw - 58, 31)
            y += 40
            # Nature list height from text
            try:
                natures.size_to_fit()
            except Exception:
                pass
            nh = max(80, min(220, natures.height or 80))
            natures.frame = (PAD, y, pw, nh)
            y += nh + 12
            abil_hdr.frame = (PAD, y, pw, 20)
            y += 24
            abil.frame = (PAD, y, pw, BTN_H)
            y += BTN_H + 14
            try:
                odds.size_to_fit()
            except Exception:
                pass
            oh = max(160, odds.height or 160)
            odds.frame = (PAD, y, pw, oh)
            y += oh + 40
            content.frame = (0, 0, w, max(h + 1, y))
            scroll.content_size = (w, content.height)

        v.layout = layout
        self._hunt_view = v
        self._setup_ability_segments()
        self._refresh_hunt()
        return v

    def _build_stat_row(self, row, which):
        for i, key in enumerate(rf.STAT_KEYS):
            b = ui.Button(title=key)
            b.name = f"{which}_{i}"
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
        key = rf.normalize_species(self.species).removeprefix("SPECIES_")
        meta = self.abilities.get("species", {}).get(key)
        seg = self._abil_seg
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
        key = rf.normalize_species(self.species).removeprefix("SPECIES_")
        meta = self.abilities.get("species", {}).get(key) or {}
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
        key = rf.normalize_species(self.species).removeprefix("SPECIES_")
        meta = self.abilities.get("species", {}).get(key)
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
        summary = self.area_row["summary"]
        natures = self._current_natures()
        without = rf.nature_matches(self.plus, self.minus, False)
        recommend = len(without) < 5 or summary.best_pct < 15.0
        self._neut_lab.text = (
            "Include neutrals (recommended)" if recommend else "Include neutrals"
        )

        nat_lines = [f"Natures {len(natures)}/25"]
        for name, up, down in natures[:10]:
            nat_lines.append(rf.format_nature_line(name, up, down))
        if len(natures) > 10:
            nat_lines.append(f"… +{len(natures) - 10} more")
        self._natures_lab.text = "\n".join(nat_lines)

        abil_label, abil_pct = self._current_ability()
        self._odds_lab.text = _odds_text(
            summary.best_pct,
            summary.best_lead,
            summary.uses_repel,
            natures,
            abil_label,
            abil_pct,
        )
        try:
            self._natures_lab.size_to_fit()
            self._odds_lab.size_to_fit()
            if hasattr(self, "_hunt_view") and self._hunt_view:
                self._hunt_view.set_needs_layout()
        except Exception:
            pass


def main() -> int:
    if ui is None:
        print("repel_gui.py needs Pythonista's ui module.")
        print("On desktop use: python3 repel_filter.py")
        return 1
    RepelApp().present()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
