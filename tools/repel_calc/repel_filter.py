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


def format_species_summary(slots: list[Slot]) -> str:
    """Bulbapedia-style aggregates derived from pret slots (not from websites)."""
    by_sp: dict[str, list[Slot]] = defaultdict(list)
    for slot in slots:
        by_sp[slot.species].append(slot)
    lines = ["Species totals (sum of pret slot rates):"]
    rows = []
    for sp, sp_slots in by_sp.items():
        total, levels = species_aggregate(sp_slots, sp)
        rows.append((total, sp, levels))
    for total, sp, levels in sorted(rows, key=lambda r: (-r[0], r[1])):
        lines.append(
            f"  {total:5.1f}%  Lv{format_level_list(levels):<8}  "
            f"{sp.replace('_', ' ').title()}"
        )
    return "\n".join(lines)


def format_slots(slots: list[Slot]) -> str:
    lines = ["Slots (pret land/water weights × per-slot min/max):"]
    for i, s in enumerate(slots):
        lv = f"{s.min_level}" if s.min_level == s.max_level else f"{s.min_level}-{s.max_level}"
        lines.append(f"  [{i:2d}] {s.rate:5.1f}%  Lv{lv:<5}  {s.pretty()}")
    return "\n".join(lines)


def _lead_range(levels: list[int]) -> str:
    levels = sorted(levels)
    if not levels:
        return "(none)"
    if levels[0] == levels[-1]:
        return f"Lv{levels[0]}"
    return f"Lv{levels[0]}-{levels[-1]}"


def format_results(target: str, results: list[LeadResult]) -> str:
    name = normalize_species(target).replace("_", " ").title()
    lines = [
        f"Repel filter analysis for {name}",
        "(allowed when wild level >= lead level)",
        "",
        f"{'Lead':>4}  {'P(target|enc)':>14}  {'target wt%':>10}  {'allowed wt%':>11}",
        "-" * 46,
    ]
    for r in results:
        cond = "  (no enc)" if r.conditional_pct is None else f"{r.conditional_pct:13.4f}%"
        lines.append(
            f"{r.lead_level:4d}  {cond:>14}  {r.absolute_pct:9.4f}%  {r.allowed_weight:10.4f}%"
        )
    valid = [r for r in results if r.conditional_pct is not None]
    lines.append("")
    if not valid:
        lines.append("No lead level yields any encounters.")
        return "\n".join(lines)
    best_c = max(r.conditional_pct for r in valid)
    best_a = max(r.absolute_pct for r in valid)
    c_leads = [r.lead_level for r in valid if r.conditional_pct == best_c]
    a_leads = [r.lead_level for r in valid if r.absolute_pct == best_a]
    lines.append(
        f"Best conditional rate: lead {_lead_range(c_leads)} -> {best_c:.4f}% are {name}"
    )
    lines.append(
        f"Best absolute weight:  lead {_lead_range(a_leads)} -> {best_a:.4f}% of rolls are {name}"
    )
    unf = next((r for r in valid if r.allowed_weight >= 99.999), None)
    if unf is not None and unf.conditional_pct == best_c:
        lines.append(
            "Repel does not improve this hunt: target is not concentrated in higher-level slots."
        )
    return "\n".join(lines)


def species_mix(slots: list[Slot], lead: int, target: str) -> str:
    target = normalize_species(target)
    weights: dict[str, float] = defaultdict(float)
    for slot in slots:
        for sp, lv, w in expand_outcomes(slot):
            if lv >= lead:
                weights[sp] += w
    total = sum(weights.values())
    lines = [f"Encounter mix at lead Lv{lead}:"]
    if total <= 0:
        lines.append("  (nothing gets through)")
        return "\n".join(lines)
    for sp, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        mark = "  <-- target" if sp == target else ""
        lines.append(f"  {100.0 * w / total:6.2f}%  {sp.replace('_', ' ').title()}{mark}")
    return "\n".join(lines)


def run_analysis(label: str, slots: list[Slot], target: str, show_slots: bool = True) -> None:
    max_wild = max(max(s.min_level, s.max_level) for s in slots)
    min_wild = min(min(s.min_level, s.max_level) for s in slots)
    results = analyze(slots, target, range(1, max_wild + 2))
    print(f"Source: {label}")
    print(f"Wild level range: {min_wild}-{max_wild}")
    print("Mechanics: Gen 3 Repel (block if wild_level < lead_level)")
    print()
    print(format_species_summary(slots))
    tgt_total, tgt_levels = species_aggregate(slots, target)
    print(
        f"Target {normalize_species(target).replace('_', ' ').title()}: "
        f"{tgt_total:g}% at Lv{format_level_list(tgt_levels)}"
    )
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
    if not items:
        print("No matches.")
        return None
    width = len(str(len(items)))
    for i, item in enumerate(items, 1):
        print(f"  {i:{width}d}) {item}")
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
            print(f"{len(hits)} {method} area(s) with {normalize_species(species).title()}:")
        elif choice == "2":
            q = input("Map filter (blank = all, e.g. ROCK_TUNNEL): ").strip()
            hits = find_areas(data, version, map_query=q or None, method=method)
            print(f"{len(hits)} matching area(s):")
        else:
            print("Invalid choice.\n")
            continue

        labels = []
        for a, b in hits:
            if choice == "1" and target_hint:
                slots = slots_from_block(b, method, data["slot_rates"])
                total, levels = species_aggregate(slots, target_hint)
                labels.append(
                    f"{a['id']} — {total:g}% Lv{format_level_list(levels)}"
                )
            else:
                names = sorted(
                    {
                        normalize_species(r[0]).replace("_", " ").title()
                        for r in b[method]
                    }
                )
                labels.append(f"{a['id']} — {a['name']}  [{', '.join(names)}]")

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
            sidx = _pick_from_list(species_on_map, "Target #: ")
            if sidx is None:
                print()
                continue
            target = species_on_map[sidx]

        print()
        run_analysis(f"{area['id']} ({version}, {method})", slots, target)
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
        print(
            f"{args.method} areas with {normalize_species(args.find).title()} "
            f"({args.version}) — rates from pret slots:"
        )
        for area, block in hits:
            slots = slots_from_block(block, args.method, data["slot_rates"])
            total, levels = species_aggregate(slots, args.find)
            print(
                f"  {area['id']:<32} {total:5.1f}%  Lv{format_level_list(levels)}"
            )
        if not hits:
            print("  (none)")
        return 0

    if args.list_maps:
        hits = find_areas(data, args.version, method=args.method)
        print(f"{args.method} areas ({args.version}, {len(hits)}):")
        for area, _ in hits:
            print(f"  {area['id']}  ({area['name']})")
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
    run_analysis(
        f"{area['id']} ({args.version}, {args.method})",
        slots,
        args.target,
        show_slots=args.show_slots,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
