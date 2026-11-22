#!/usr/bin/env python3
"""
Gen 3 Repel / encounter-rate calculator (FireRed / LeafGreen).

Rule (IsWildLevelAllowedByRepel): with Repel active, a wild mon appears only
when wild_level >= lead_level. Blocked rolls cancel the encounter (no re-roll).

This is a general tool: you supply any encounter table. No game data is
embedded. Optional: if wild_encounters.json is present, --map can load a map.

iPhone / Pythonista
-------------------
1. Copy only this file into Pythonista.
2. Run it (no arguments) for the interactive menu.
3. Paste a table, or open a .txt table you saved beside the script.

Table formats (lines; # comments ok)
------------------------------------
Aggregate (Bulbapedia-style):
    Zubat   15-16  30
    Mankey  16-17  15
    Machop  17     10
    Geodude 15-17  35
    Onix    13-17  10

Exact slots (rate first — preferred when you know slot levels):
    20 Zubat 16
    20 Geodude 17
    10 Mankey 17
    5  Onix 13
    4  Onix 15
    1  Onix 17

Or call from another script:
    import repel_filter
    repel_filter.main([])
    repel_filter.main(["--table", "my_area.txt", "--target", "Onix"])
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


LAND_SLOT_RATES = (20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "tools" else SCRIPT_DIR

# species  levels  rate%   OR   rate%  species  levels
_LINE_RATE_FIRST = re.compile(
    r"^(?P<rate>\d+(?:\.\d+)?)\s*%?\s+"
    r"(?P<species>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?P<lo>\d+)(?:\s*-\s*(?P<hi>\d+))?$"
)
_LINE_SPECIES_FIRST = re.compile(
    r"^(?P<species>[A-Za-z][A-Za-z0-9_]*)\s+"
    r"(?P<lo>\d+)(?:\s*-\s*(?P<hi>\d+))?\s+"
    r"(?P<rate>\d+(?:\.\d+)?)\s*%?$"
)


@dataclass(frozen=True)
class Slot:
    species: str
    min_level: int
    max_level: int
    rate: float

    def levels(self) -> range:
        lo, hi = sorted((self.min_level, self.max_level))
        return range(lo, hi + 1)

    def pretty_species(self) -> str:
        name = self.species
        if name.startswith("SPECIES_"):
            name = name[len("SPECIES_") :]
        return name.replace("_", " ").title()


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
    name = name.strip().upper().replace(" ", "_")
    if not name.startswith("SPECIES_"):
        name = "SPECIES_" + name
    return name


def expand_slot_outcomes(slot: Slot) -> list[tuple[str, int, float]]:
    levels = list(slot.levels())
    if not levels:
        return []
    per_level = slot.rate / len(levels)
    return [(slot.species, level, per_level) for level in levels]


def analyze(
    slots: Iterable[Slot],
    target: str,
    lead_levels: Iterable[int],
) -> list[LeadResult]:
    target = normalize_species(target)
    outcomes: list[tuple[str, int, float]] = []
    for slot in slots:
        outcomes.extend(expand_slot_outcomes(slot))

    results: list[LeadResult] = []
    for lead in lead_levels:
        allowed = [(sp, lv, w) for sp, lv, w in outcomes if lv >= lead]
        target_w = sum(w for sp, _, w in allowed if sp == target)
        allowed_w = sum(w for _, _, w in allowed)
        conditional = (100.0 * target_w / allowed_w) if allowed_w > 0 else None
        results.append(
            LeadResult(
                lead_level=lead,
                target_weight=target_w,
                allowed_weight=allowed_w,
                conditional_pct=conditional,
            )
        )
    return results


def parse_table_text(text: str) -> list[Slot]:
    """Parse aggregate or slot lines into Slot list."""
    slots: list[Slot] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Allow comma-separated copies pasted from spreadsheets.
        line = line.replace(",", " ")
        line = re.sub(r"\s+", " ", line)
        m = _LINE_RATE_FIRST.match(line) or _LINE_SPECIES_FIRST.match(line)
        if not m:
            raise ValueError(f"Could not parse encounter line: {raw!r}")
        lo = int(m.group("lo"))
        hi = int(m.group("hi") or lo)
        slots.append(
            Slot(
                species=normalize_species(m.group("species")),
                min_level=lo,
                max_level=hi,
                rate=float(m.group("rate")),
            )
        )
    if not slots:
        raise ValueError("No encounter lines found.")
    total = sum(s.rate for s in slots)
    if abs(total - 100.0) > 0.05:
        # Soft warning only — some tables are partial or use different bases.
        print(f"Note: rates sum to {total:g}% (usually 100%).")
    return slots


def parse_table_file(path: Path) -> list[Slot]:
    return parse_table_text(path.read_text())


def find_encounters_json(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit if explicit.is_file() else None
    candidates = [
        REPO_ROOT / "src" / "data" / "wild_encounters.json",
        SCRIPT_DIR / "wild_encounters.json",
        Path.cwd() / "wild_encounters.json",
        Path.cwd() / "src" / "data" / "wild_encounters.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def _land_rates_for_group(group: dict) -> tuple[float, ...]:
    for field in group.get("fields", []):
        if field.get("type") == "land_mons":
            return tuple(field["encounter_rates"])
    return LAND_SLOT_RATES


def _version_matches(label: str, version: str | None) -> bool:
    if not version:
        return True
    if version.lower() == "firered" and "LeafGreen" in label:
        return False
    if version.lower() == "leafgreen" and "FireRed" in label:
        return False
    return True


def list_land_maps(encounters_path: Path, version: str | None = None) -> list[tuple[str, str]]:
    data = json.loads(encounters_path.read_text())
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for group in data["wild_encounter_groups"]:
        for enc in group.get("encounters", []):
            if not enc.get("land_mons"):
                continue
            map_name = enc.get("map", "")
            label = enc.get("base_label", map_name)
            if not _version_matches(label, version):
                continue
            short = map_name[4:] if map_name.startswith("MAP_") else map_name
            if short in seen:
                continue
            seen.add(short)
            rows.append((short, label))
    rows.sort(key=lambda row: row[0])
    return rows


def load_map_land_slots(
    encounters_path: Path,
    map_name: str,
    version: str | None = None,
) -> tuple[str, list[Slot]]:
    data = json.loads(encounters_path.read_text())
    map_key = map_name if map_name.startswith("MAP_") else f"MAP_{map_name}"
    map_key = map_key.upper()

    matches: list[tuple[str, list[Slot]]] = []
    for group in data["wild_encounter_groups"]:
        rates = _land_rates_for_group(group)
        for enc in group.get("encounters", []):
            if enc.get("map") != map_key:
                continue
            land = enc.get("land_mons")
            if not land:
                continue
            label = enc.get("base_label", map_key)
            if not _version_matches(label, version):
                continue
            mons = land["mons"]
            if len(mons) != len(rates):
                raise SystemExit(
                    f"{label}: expected {len(rates)} land slots, found {len(mons)}"
                )
            slots = [
                Slot(
                    species=normalize_species(m["species"]),
                    min_level=int(m["min_level"]),
                    max_level=int(m["max_level"]),
                    rate=float(rates[i]),
                )
                for i, m in enumerate(mons)
            ]
            matches.append((label, slots))

    if not matches:
        raise SystemExit(f"No land encounters found for {map_key}.")
    if len(matches) > 1 and not version:
        labels = ", ".join(label for label, _ in matches)
        raise SystemExit(
            f"Multiple versions for {map_key}: {labels}. Pass --version firered|leafgreen."
        )
    return matches[0]


def format_slot_summary(slots: list[Slot]) -> str:
    lines = ["Slots (rate%  levels  species):"]
    for i, slot in enumerate(slots):
        lv = (
            f"{slot.min_level}"
            if slot.min_level == slot.max_level
            else f"{slot.min_level}-{slot.max_level}"
        )
        lines.append(f"  [{i:2d}] {slot.rate:5.1f}%  Lv{lv:<5}  {slot.pretty_species()}")
    return "\n".join(lines)


def _lead_range_str(levels: list[int]) -> str:
    if not levels:
        return "(none)"
    levels = sorted(levels)
    if levels[0] == levels[-1]:
        return f"Lv{levels[0]}"
    return f"Lv{levels[0]}-{levels[-1]}"


def format_results(target: str, results: list[LeadResult]) -> str:
    target_name = normalize_species(target)[len("SPECIES_") :].replace("_", " ").title()
    lines = [
        f"Repel filter analysis for {target_name}",
        "(allowed when wild level >= lead level)",
        "",
        f"{'Lead':>4}  {'P(target|enc)':>14}  {'target wt%':>10}  {'allowed wt%':>11}",
        "-" * 46,
    ]
    for r in results:
        if r.conditional_pct is None:
            cond = "  (no enc)"
        else:
            cond = f"{r.conditional_pct:13.4f}%"
        lines.append(
            f"{r.lead_level:4d}  {cond:>14}  {r.absolute_pct:9.4f}%  {r.allowed_weight:10.4f}%"
        )

    valid = [r for r in results if r.conditional_pct is not None]
    lines.append("")
    if not valid:
        lines.append("No lead level yields any encounters.")
        return "\n".join(lines)

    best_cond_val = max(r.conditional_pct for r in valid)
    best_abs_val = max(r.absolute_pct for r in valid)
    best_cond_leads = [r.lead_level for r in valid if r.conditional_pct == best_cond_val]
    best_abs_leads = [r.lead_level for r in valid if r.absolute_pct == best_abs_val]

    lines.append(
        f"Best conditional rate: lead {_lead_range_str(best_cond_leads)} "
        f"-> {best_cond_val:.4f}% of encounters are {target_name}"
    )
    lines.append(
        f"Best absolute weight:  lead {_lead_range_str(best_abs_leads)} "
        f"-> {best_abs_val:.4f}% of land rolls are {target_name}"
    )
    if set(best_cond_leads) != set(best_abs_leads):
        lines.append(
            "Note: encounter purity and raw target rolls can peak at different leads."
        )
    unfiltered = next((r for r in valid if r.allowed_weight >= 99.999), None)
    if unfiltered is not None and unfiltered.conditional_pct == best_cond_val:
        lines.append(
            "Repel does not improve this hunt: the target is not concentrated in higher-level slots."
        )
    return "\n".join(lines)


def species_breakdown(slots: list[Slot], lead: int, target: str) -> str:
    target = normalize_species(target)
    weights: dict[str, float] = defaultdict(float)
    for slot in slots:
        for sp, lv, w in expand_slot_outcomes(slot):
            if lv >= lead:
                weights[sp] += w
    total = sum(weights.values())
    lines = [f"Encounter mix at lead Lv{lead}:"]
    if total <= 0:
        lines.append("  (nothing gets through)")
        return "\n".join(lines)
    for sp, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        name = sp[len("SPECIES_") :].replace("_", " ").title()
        mark = "  <-- target" if sp == target else ""
        lines.append(f"  {100.0 * w / total:6.2f}%  {name}{mark}")
    return "\n".join(lines)


def run_analysis(
    label: str,
    slots: list[Slot],
    target: str,
    show_slots: bool = True,
    breakdown: int | None = None,
    min_lead: int = 1,
    max_lead: int | None = None,
) -> None:
    max_wild = max(max(s.min_level, s.max_level) for s in slots)
    min_wild = min(min(s.min_level, s.max_level) for s in slots)
    hi = max_lead if max_lead is not None else max_wild + 1
    results = analyze(slots, target, range(min_lead, hi + 1))

    print(f"Source: {label}")
    print(f"Wild level range: {min_wild}-{max_wild}")
    print("Mechanics: Gen 3 Repel (block if wild_level < lead_level)")
    print()
    if show_slots:
        print(format_slot_summary(slots))
        print()

    interesting = [r for r in results if r.lead_level >= min_wild - 1]
    print(format_results(target, interesting if interesting else results))

    if breakdown is not None:
        print()
        print(species_breakdown(slots, breakdown, target))

    valid = [r for r in results if r.conditional_pct is not None]
    if valid:
        best_val = max(r.conditional_pct for r in valid)
        best = max(
            (r for r in valid if r.conditional_pct == best_val),
            key=lambda r: r.lead_level,
        )
        print()
        print(species_breakdown(slots, best.lead_level, target))


def _read_multiline(prompt_header: str) -> str:
    print(prompt_header)
    print("Enter lines, then a blank line when done:")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "" and lines:
            break
        if line.strip() == "" and not lines:
            continue
        lines.append(line)
    return "\n".join(lines)


def interactive_menu(encounters_path: Path | None, version: str) -> int:
    print("Gen 3 encounter / Repel calculator")
    print("No game data required — paste any table.")
    if encounters_path:
        print(f"Optional JSON available: {encounters_path.name}")
    print()

    while True:
        print("1) Paste encounter table")
        print("2) Load table from .txt file")
        if encounters_path:
            print("3) Load map from wild_encounters.json")
            print("4) List maps in JSON")
        else:
            print("3) Load map from JSON (not found)")
            print("4) List maps (not found)")
        print("0) Quit")
        choice = input("> ").strip()

        if choice in ("0", "q", "quit", "exit"):
            return 0

        slots: list[Slot] | None = None
        label = ""

        if choice == "1":
            text = _read_multiline(
                "Paste species/level/rate lines "
                '(e.g. "Onix 13-17 10" or "5 Onix 13").'
            )
            try:
                slots = parse_table_text(text)
            except ValueError as exc:
                print(f"Error: {exc}\n")
                continue
            label = "pasted table"
        elif choice == "2":
            path_str = input("Path to .txt table: ").strip()
            if not path_str:
                continue
            path = Path(path_str).expanduser()
            if not path.is_file():
                # Also try beside the script (Pythonista-friendly).
                alt = SCRIPT_DIR / path_str
                path = alt if alt.is_file() else path
            if not path.is_file():
                print(f"File not found: {path_str}\n")
                continue
            try:
                slots = parse_table_file(path)
            except ValueError as exc:
                print(f"Error: {exc}\n")
                continue
            label = str(path)
        elif choice == "3":
            if not encounters_path:
                print(
                    "Place wild_encounters.json next to this script to enable map load.\n"
                )
                continue
            map_name = input("Map name (e.g. ROCK_TUNNEL_B1F): ").strip()
            if not map_name:
                continue
            try:
                label, slots = load_map_land_slots(encounters_path, map_name, version)
            except SystemExit as exc:
                print(f"{exc}\n")
                continue
        elif choice == "4":
            if not encounters_path:
                print("No wild_encounters.json found.\n")
                continue
            rows = list_land_maps(encounters_path, version)
            print(f"Maps with land encounters ({version}, {len(rows)}):")
            for short, lab in rows:
                print(f"  {short}  ({lab})")
            print()
            continue
        else:
            print("Invalid choice.\n")
            continue

        target = input("Target species: ").strip()
        if not target:
            print("Target is required.\n")
            continue

        print()
        run_analysis(label, slots, target, show_slots=True)
        print()
        again = input("Another? [Y/n] ").strip().lower()
        if again in ("n", "no"):
            return 0
        print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="General Gen 3 Repel / encounter-rate calculator."
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--table",
        type=Path,
        help="Path to a .txt encounter table (species/level/rate lines)",
    )
    src.add_argument(
        "--map",
        help="Map constant from wild_encounters.json (optional; needs that file)",
    )
    src.add_argument(
        "--list-maps",
        action="store_true",
        help="List maps from wild_encounters.json, then exit",
    )
    src.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive menu (default when run with no args)",
    )
    p.add_argument("--target", default=None, help="Target species (required for analysis)")
    p.add_argument(
        "--version",
        choices=("firered", "leafgreen"),
        default="firered",
        help="Version when using --map (default: firered)",
    )
    p.add_argument(
        "--encounters",
        type=Path,
        default=None,
        help="Path to wild_encounters.json (optional)",
    )
    p.add_argument("--min-lead", type=int, default=1)
    p.add_argument("--max-lead", type=int, default=None)
    p.add_argument("--show-slots", action="store_true")
    p.add_argument("--breakdown", type=int, metavar="LEAD")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    encounters = find_encounters_json(None)

    if not argv or argv == ["--interactive"]:
        return interactive_menu(find_encounters_json(None), "firered")

    args = parse_args(argv)
    encounters = find_encounters_json(args.encounters)

    if args.interactive:
        return interactive_menu(encounters, args.version)

    if args.list_maps:
        if encounters is None:
            raise SystemExit(
                "wild_encounters.json not found. "
                "Pass --encounters PATH, or use --table / interactive paste instead."
            )
        rows = list_land_maps(encounters, args.version)
        print(f"Maps with land encounters ({args.version}, {len(rows)}):")
        for short, label in rows:
            print(f"  {short}  ({label})")
        return 0

    if args.table is not None:
        label = str(args.table)
        slots = parse_table_file(args.table)
    elif args.map:
        if encounters is None:
            raise SystemExit(
                "wild_encounters.json not found for --map. "
                "Use --table, paste in --interactive, or pass --encounters PATH."
            )
        label, slots = load_map_land_slots(encounters, args.map, args.version)
    else:
        raise SystemExit("Specify --table, --map, --list-maps, or --interactive.")

    if not args.target:
        raise SystemExit("--target SPECIES is required for analysis.")

    run_analysis(
        label,
        slots,
        args.target,
        show_slots=args.show_slots,
        breakdown=args.breakdown,
        min_lead=args.min_lead,
        max_lead=args.max_lead,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
