#!/usr/bin/env python3
"""
Gen 3 Repel / encounter-rate calculator for FireRed & LeafGreen.

Ships with encounters.json (exported from the decomp). Pick a map and target
species — no website copy/paste required.

Pythonista: copy this whole folder (repel_filter.py + encounters.json), then run
repel_filter.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


HERE = Path(__file__).resolve().parent
DATA_FILE = HERE / "encounters.json"

METHOD_RATES_KEY = {
    "land": "land",
    "water": "water",
    "rock_smash": "rock_smash",
}


def friendly_map_name(map_id: str, stored: str | None = None) -> str:
    """ROUTE7 -> 'Route 7' so Route 7 vs Route 8 is obvious in the UI."""
    parts = []
    for part in map_id.split("_"):
        # Only split when the token is letters + pure digits (ROUTE7), not B1F.
        m = re.match(r"^([A-Za-z]+)(\d+)$", part)
        if m:
            parts.append(f"{m.group(1).title()} {m.group(2)}")
        else:
            parts.append(part.title() if part.isalpha() else part)
    return " ".join(parts)


@dataclass(frozen=True)
class Slot:
    species: str
    min_level: int
    max_level: int
    rate: float

    def levels(self) -> range:
        lo, hi = sorted((self.min_level, self.max_level))
        return range(lo, hi + 1)

    def pretty(self) -> str:
        return self.species.replace("_", " ").title()


@dataclass(frozen=True)
class LeadResult:
    lead_level: int
    target_weight: float
    allowed_weight: float
    conditional_pct: float | None

    @property
    def absolute_pct(self) -> float:
        return self.target_weight


def normalize_species(name: str) -> str:
    return name.strip().upper().replace(" ", "_")


def expand_outcomes(slot: Slot) -> list[tuple[str, int, float]]:
    levels = list(slot.levels())
    per = slot.rate / len(levels)
    return [(slot.species, lv, per) for lv in levels]


def analyze(slots: Iterable[Slot], target: str, leads: Iterable[int]) -> list[LeadResult]:
    target = normalize_species(target)
    outcomes: list[tuple[str, int, float]] = []
    for slot in slots:
        outcomes.extend(expand_outcomes(slot))
    results = []
    for lead in leads:
        allowed = [(sp, lv, w) for sp, lv, w in outcomes if lv >= lead]
        tw = sum(w for sp, _, w in allowed if sp == target)
        aw = sum(w for _, _, w in allowed)
        results.append(
            LeadResult(lead, tw, aw, (100.0 * tw / aw) if aw else None)
        )
    return results


def load_data(path: Path | None = None) -> dict:
    path = path or DATA_FILE
    if not path.is_file():
        raise SystemExit(
            f"Missing {path.name}. Run export_encounters.py in the decomp, "
            "or keep encounters.json next to this script."
        )
    return json.loads(path.read_text())


def area_block(area: dict, version: str) -> dict | None:
    if "encounters" in area:
        return area["encounters"]
    return area.get(version)


def slots_from_block(block: dict, method: str, slot_rates: dict) -> list[Slot]:
    rows = block.get(method)
    if not rows:
        return []
    rates = slot_rates[METHOD_RATES_KEY[method]]
    if len(rows) != len(rates):
        raise SystemExit(
            f"{method}: expected {len(rates)} slots, found {len(rows)}"
        )
    return [
        Slot(normalize_species(sp), int(lo), int(hi), float(rates[i]))
        for i, (sp, lo, hi) in enumerate(rows)
    ]


def find_areas(
    data: dict,
    version: str,
    *,
    map_query: str | None = None,
    species: str | None = None,
    method: str = "land",
) -> list[tuple[dict, dict]]:
    """Return (area, block) matches."""
    mq = map_query.upper().replace(" ", "_") if map_query else None
    sp = normalize_species(species) if species else None
    hits = []
    for area in data["areas"]:
        block = area_block(area, version)
        if not block or method not in block:
            continue
        if mq and mq not in area["id"].upper() and mq not in area["name"].upper().replace(" ", "_"):
            continue
        if sp:
            if not any(normalize_species(row[0]) == sp for row in block[method]):
                continue
        hits.append((area, block))
    return hits


def species_aggregate(slots: list[Slot], species: str) -> tuple[float, list[int]]:
    """Sum pret slot rates for one species; collect distinct levels."""
    species = normalize_species(species)
    total = 0.0
    levels: set[int] = set()
    for slot in slots:
        if slot.species != species:
            continue
        total += slot.rate
        levels.update(slot.levels())
    return total, sorted(levels)


def format_level_list(levels: list[int]) -> str:
    if not levels:
        return "?"
    if len(levels) == 1:
        return str(levels[0])
    # Contiguous range -> "15-18"; otherwise comma list.
    if levels[-1] - levels[0] + 1 == len(levels):
        return f"{levels[0]}-{levels[-1]}"
    return ",".join(str(lv) for lv in levels)


def _pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%"


def format_species_summary(slots: list[Slot]) -> str:
    """Species aggregates from pret slots — short lines for phone wraps."""
    by_sp: dict[str, list[Slot]] = defaultdict(list)
    for slot in slots:
        by_sp[slot.species].append(slot)
    lines = ["Species totals:"]
    rows = []
    for sp, sp_slots in by_sp.items():
        total, levels = species_aggregate(sp_slots, sp)
        rows.append((total, sp, levels))
    for total, sp, levels in sorted(rows, key=lambda r: (-r[0], r[1])):
        name = sp.replace("_", " ").title()
        lines.append(f"  {_pct(total)} Lv{format_level_list(levels)}")
        lines.append(f"    {name}")
    return "\n".join(lines)


def format_slots(slots: list[Slot]) -> str:
    lines = ["Slots (pret weights):"]
    for i, s in enumerate(slots):
        lv = f"{s.min_level}" if s.min_level == s.max_level else f"{s.min_level}-{s.max_level}"
        lines.append(f"  [{i}] {_pct(s.rate)} Lv{lv}")
        lines.append(f"      {s.pretty()}")
    return "\n".join(lines)


def _lead_range(levels: list[int]) -> str:
    levels = sorted(levels)
    if not levels:
        return "(none)"
    if levels[0] == levels[-1]:
        return f"Lv{levels[0]}"
    return f"Lv{levels[0]}-{levels[-1]}"


def format_results(target: str, results: list[LeadResult]) -> str:
    """Narrow repel table (~32 cols) for iPhone / Pythonista."""
    name = normalize_species(target).replace("_", " ").title()
    lines = [
        f"Repel: {name}",
        "wild OK if Lv >= lead",
        "",
        "Lead  of_enc  rolls  thru",
        "----  ------  -----  ----",
    ]
    for r in results:
        if r.conditional_pct is None:
            lines.append(f"{r.lead_level:>4}  (no encounters)")
            continue
        lines.append(
            f"{r.lead_level:>4}  {_pct(r.conditional_pct):>6}  "
            f"{_pct(r.absolute_pct):>5}  {_pct(r.allowed_weight, 0):>4}"
        )
    valid = [r for r in results if r.conditional_pct is not None]
    lines.append("")
    if not valid:
        lines.append("No lead yields encounters.")
        return "\n".join(lines)
    best_c = max(r.conditional_pct for r in valid)
    best_a = max(r.absolute_pct for r in valid)
    c_leads = [r.lead_level for r in valid if r.conditional_pct == best_c]
    a_leads = [r.lead_level for r in valid if r.absolute_pct == best_a]
    lines.append(f"Best of_enc: {_lead_range(c_leads)}")
    lines.append(f"  {_pct(best_c)} are {name}")
    lines.append(f"Best rolls: {_lead_range(a_leads)}")
    lines.append(f"  {_pct(best_a)} of land rolls")
    unf = next((r for r in valid if r.allowed_weight >= 99.999), None)
    if unf is not None and unf.conditional_pct == best_c:
        lines.append("Repel does not help here.")
    return "\n".join(lines)


def species_mix(slots: list[Slot], lead: int, target: str) -> str:
    target = normalize_species(target)
    weights: dict[str, float] = defaultdict(float)
    for slot in slots:
        for sp, lv, w in expand_outcomes(slot):
            if lv >= lead:
                weights[sp] += w
    total = sum(weights.values())
    lines = [f"Mix at lead Lv{lead}:"]
    if total <= 0:
        lines.append("  (nothing gets through)")
        return "\n".join(lines)
    for sp, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = " *" if sp == target else ""
        lines.append(f"  {_pct(100.0 * w / total)}")
        lines.append(f"    {sp.replace('_', ' ').title()}{mark}")
    return "\n".join(lines)


def format_area_choice(
    index: int,
    area: dict,
    *,
    rate: float | None = None,
    levels: list[int] | None = None,
    species_names: list[str] | None = None,
) -> str:
    """Multi-line menu entry so phone wrap doesn't smash columns."""
    nice = friendly_map_name(area["id"], area.get("name"))
    lines = [f"{index}) {nice}", f"   {area['id']}"]
    if rate is not None and levels is not None:
        lines.append(f"   {_pct(rate)} Lv{format_level_list(levels)}")
    elif species_names:
        # Keep one short species line; truncate if huge.
        joined = ", ".join(species_names)
        if len(joined) > 34:
            joined = joined[:31] + "..."
        lines.append(f"   {joined}")
    return "\n".join(lines)


def run_analysis(label: str, slots: list[Slot], target: str, show_slots: bool = True) -> None:
    max_wild = max(max(s.min_level, s.max_level) for s in slots)
    min_wild = min(min(s.min_level, s.max_level) for s in slots)
    results = analyze(slots, target, range(1, max_wild + 2))
    # Stack source fields — avoid one long wrapped line on phones.
    print("Source:")
    for part in label.split(" — "):
        print(f"  {part}")
    print(f"Levels: {min_wild}-{max_wild}")
    print("Repel: wild Lv >= lead")
    print()
    print(format_species_summary(slots))
    tgt_total, tgt_levels = species_aggregate(slots, target)
    print()
    print(f"Target: {normalize_species(target).replace('_', ' ').title()}")
    print(f"  {_pct(tgt_total)} Lv{format_level_list(tgt_levels)}")
    print()
    if show_slots:
        print(format_slots(slots))
        print()
    interesting = [r for r in results if r.lead_level >= min_wild - 1]
    print(format_results(target, interesting))
    valid = [r for r in results if r.conditional_pct is not None]
    if valid:
        best = max(r.conditional_pct for r in valid)
        lead = max(r.lead_level for r in valid if r.conditional_pct == best)
        print()
        print(species_mix(slots, lead, target))


def _pick_from_list(items: list[str], prompt: str) -> int | None:
    """items are multi-line blocks already numbered by the caller."""
    if not items:
        print("No matches.")
        return None
    for i, item in enumerate(items):
        print(item)
        if i < len(items) - 1:
            print()
    raw = input(prompt).strip().lower()
    if raw in ("", "q", "0"):
        return None
    if not raw.isdigit() or not (1 <= int(raw) <= len(items)):
        print("Invalid selection.")
        return None
    return int(raw) - 1


def interactive(data: dict, default_version: str = "firered") -> int:
    version = default_version
    method = "land"
    print("FR/LG Repel calculator")
    print(f"Data: {DATA_FILE.name} ({len(data['areas'])} areas)")
    print()

    while True:
        print(f"Version: {version}   Method: {method}")
        print("1) Find species (recommended)")
        print("2) Browse / search maps")
        print("3) Switch version (firered / leafgreen)")
        print("4) Switch method (land / water / rock_smash)")
        print("0) Quit")
        choice = input("> ").strip()

        if choice in ("0", "q", "quit"):
            return 0
        if choice == "3":
            version = "leafgreen" if version == "firered" else "firered"
            print(f"Now using {version}\n")
            continue
        if choice == "4":
            opts = ["land", "water", "rock_smash"]
            idx = _pick_from_list(opts, "Method #: ")
            if idx is not None:
                method = opts[idx]
            print()
            continue

        hits: list[tuple[dict, dict]] = []
        target_hint = None

        if choice == "1":
            species = input("Species (e.g. Onix): ").strip()
            if not species:
                continue
            hits = find_areas(data, version, species=species, method=method)
            target_hint = species
            # Sort by pret aggregate rate (high first) so Route 8 Growlithe
            # (20%) appears before Route 7 (10%), matching common hunt guides.
            def _hit_rate(item: tuple[dict, dict]) -> float:
                area, block = item
                slots = slots_from_block(block, method, data["slot_rates"])
                total, _ = species_aggregate(slots, species)
                return total

            hits = sorted(hits, key=lambda h: (-_hit_rate(h), h[0]["id"]))
            print(f"{normalize_species(species).title()}")
            print(f"{len(hits)} {method} areas")
            print()
        elif choice == "2":
            q = input("Map filter (blank = all): ").strip()
            hits = find_areas(data, version, map_query=q or None, method=method)
            print(f"{len(hits)} areas")
            print()
        else:
            print("Invalid choice.\n")
            continue

        labels = []
        for i, (a, b) in enumerate(hits, 1):
            if choice == "1" and target_hint:
                slots = slots_from_block(b, method, data["slot_rates"])
                total, levels = species_aggregate(slots, target_hint)
                labels.append(
                    format_area_choice(i, a, rate=total, levels=levels)
                )
            else:
                names = sorted(
                    {
                        normalize_species(r[0]).replace("_", " ").title()
                        for r in b[method]
                    }
                )
                labels.append(format_area_choice(i, a, species_names=names))

        idx = _pick_from_list(labels, "Area #: ")
        if idx is None:
            print()
            continue
        area, block = hits[idx]
        slots = slots_from_block(block, method, data["slot_rates"])
        species_on_map = sorted({s.pretty() for s in slots})
        if target_hint:
            target = target_hint
        else:
            print("Species on this map:")
            print()
            sp_labels = [f"{i}) {name}" for i, name in enumerate(species_on_map, 1)]
            sidx = _pick_from_list(sp_labels, "Target #: ")
            if sidx is None:
                print()
                continue
            target = species_on_map[sidx]

        print()
        nice = friendly_map_name(area["id"], area.get("name"))
        run_analysis(
            f"{area['id']} — {nice} — {version}/{method}",
            slots,
            target,
        )
        print()
        again = input("Another? [Y/n] ").strip().lower()
        if again in ("n", "no"):
            return 0
        print()


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, default=DATA_FILE, help="Path to encounters.json")
    p.add_argument("--version", choices=("firered", "leafgreen"), default="firered")
    p.add_argument("--method", choices=("land", "water", "rock_smash"), default="land")
    p.add_argument("--map", help="Map id, e.g. ROCK_TUNNEL_B1F")
    p.add_argument("--target", help="Target species, e.g. Onix")
    p.add_argument("--find", help="List areas containing this species, then exit")
    p.add_argument("--list-maps", action="store_true", help="List areas for the version/method")
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--show-slots", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv or argv == ["--interactive"]:
        data = load_data()
        return interactive(data)

    args = parse_args(argv)
    data = load_data(args.data)

    if args.interactive:
        return interactive(data, args.version)

    if args.find:
        hits = find_areas(data, args.version, species=args.find, method=args.method)

        def _rate(item: tuple[dict, dict]) -> float:
            _, block = item
            slots = slots_from_block(block, args.method, data["slot_rates"])
            total, _ = species_aggregate(slots, args.find)
            return total

        hits = sorted(hits, key=lambda h: (-_rate(h), h[0]["id"]))
        print(normalize_species(args.find).title())
        print(f"{args.version} / {args.method}")
        print(f"{len(hits)} areas (pret slots)")
        print()
        if not hits:
            print("(none)")
            return 0
        for i, (area, block) in enumerate(hits, 1):
            slots = slots_from_block(block, args.method, data["slot_rates"])
            total, levels = species_aggregate(slots, args.find)
            print(format_area_choice(i, area, rate=total, levels=levels))
            if i < len(hits):
                print()
        return 0

    if args.list_maps:
        hits = find_areas(data, args.version, method=args.method)
        print(f"{args.method} / {args.version}")
        print(f"{len(hits)} areas")
        print()
        for i, (area, _) in enumerate(hits, 1):
            print(format_area_choice(i, area))
            if i < len(hits):
                print()
        return 0

    if not args.map or not args.target:
        raise SystemExit("Use --map and --target, or run with no args for the menu.")

    hits = find_areas(data, args.version, map_query=args.map, method=args.method)
    # Prefer exact id match
    exact = [h for h in hits if h[0]["id"] == args.map.upper()]
    if exact:
        hits = exact
    if not hits:
        raise SystemExit(f"No {args.method} data for map {args.map!r} ({args.version}).")
    if len(hits) > 1:
        ids = ", ".join(a["id"] for a, _ in hits)
        raise SystemExit(f"Ambiguous map {args.map!r}: {ids}")
    area, block = hits[0]
    slots = slots_from_block(block, args.method, data["slot_rates"])
    nice = friendly_map_name(area["id"], area.get("name"))
    run_analysis(
        f"{area['id']} — {nice} — {args.version}/{args.method}",
        slots,
        args.target,
        show_slots=args.show_slots,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
