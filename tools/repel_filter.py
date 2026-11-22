#!/usr/bin/env python3
"""
Gen 3 Repel filter calculator (FireRed / LeafGreen).

With a Repel active, a wild encounter is allowed only when
wild_level >= lead_level (see IsWildLevelAllowedByRepel in src/wild_encounter.c).
Blocked rolls cancel the encounter; they do not re-roll the slot.

Standalone / Pythonista:
  Copy only this file. Built-in Rock Tunnel tables need no src/ data.
  Run the file with no arguments for an interactive menu, or:

    import repel_filter
    repel_filter.main([])                 # menu
    repel_filter.main(["--interactive"])
    repel_filter.main(["--map", "ROCK_TUNNEL_B1F", "--show-slots"])

Optional: place wild_encounters.json beside this script (or keep the repo
layout) to unlock every map via --map / --list-maps.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


# Land slot weights from wild_encounters.json field encounter_rates (sum = 100).
LAND_SLOT_RATES = (20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent if SCRIPT_DIR.name == "tools" else SCRIPT_DIR


@dataclass(frozen=True)
class Slot:
    species: str
    min_level: int
    max_level: int
    rate: float  # percent of all land rolls that pick this slot

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
    conditional_pct: float | None  # None if no encounters possible

    @property
    def absolute_pct(self) -> float:
        """Target weight as percent of unfiltered land rolls."""
        return self.target_weight


def normalize_species(name: str) -> str:
    name = name.strip().upper().replace(" ", "_")
    if not name.startswith("SPECIES_"):
        name = "SPECIES_" + name
    return name


def expand_slot_outcomes(slot: Slot) -> list[tuple[str, int, float]]:
    """Return (species, level, weight%) outcomes for one slot."""
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
    outcomes = []
    for slot in slots:
        outcomes.extend(expand_slot_outcomes(slot))

    results: list[LeadResult] = []
    for lead in lead_levels:
        # Gen 3: wild_level < lead_level is blocked.
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


def slots_from_rows(
    rows: Sequence[tuple[str, int, int]] | Sequence[tuple[str, int, int, float]],
    rates: Sequence[float] = LAND_SLOT_RATES,
) -> list[Slot]:
    """Build slots from (species, min, max[, rate]) rows."""
    slots: list[Slot] = []
    for i, row in enumerate(rows):
        if len(row) == 4:
            sp, lo, hi, rate = row  # type: ignore[misc]
        else:
            sp, lo, hi = row  # type: ignore[misc]
            rate = float(rates[i])
        slots.append(
            Slot(
                species=normalize_species(sp),
                min_level=int(lo),
                max_level=int(hi),
                rate=float(rate),
            )
        )
    return slots


# Exact FR/LG land slots (embedded so this file runs without wild_encounters.json).
# Source: src/data/wild_encounters.json — FireRed Rock Tunnel (LeafGreen identical).
BUILTIN_AREAS: dict[str, tuple[str, list[Slot]]] = {
    "ROCK_TUNNEL_B1F": (
        "Rock Tunnel B1F (built-in FR/LG slots)",
        slots_from_rows(
            [
                ("Zubat", 16, 16),
                ("Geodude", 17, 17),
                ("Mankey", 17, 17),
                ("Geodude", 16, 16),
                ("Zubat", 15, 15),
                ("Machop", 17, 17),
                ("Mankey", 16, 16),
                ("Onix", 13, 13),
                ("Geodude", 15, 15),
                ("Onix", 15, 15),
                ("Geodude", 15, 15),
                ("Onix", 17, 17),
            ]
        ),
    ),
    "ROCK_TUNNEL_1F": (
        "Rock Tunnel 1F (built-in FR/LG slots)",
        slots_from_rows(
            [
                ("Zubat", 15, 15),
                ("Geodude", 16, 16),
                ("Mankey", 16, 16),
                ("Geodude", 17, 17),
                ("Zubat", 16, 16),
                ("Machop", 16, 16),
                ("Mankey", 17, 17),
                ("Machop", 17, 17),
                ("Geodude", 15, 15),
                ("Onix", 13, 13),
                ("Geodude", 15, 15),
                ("Onix", 15, 15),
            ]
        ),
    ),
    "USER_TABLE": (
        "Rock Tunnel aggregate table (Bulbapedia-style; approx.)",
        slots_from_rows(
            [
                ("Zubat", 15, 16, 30.0),
                ("Mankey", 16, 17, 15.0),
                ("Machop", 17, 17, 10.0),
                ("Geodude", 15, 17, 35.0),
                ("Onix", 13, 17, 10.0),
            ]
        ),
    ),
}


def find_encounters_json(explicit: Path | None = None) -> Path | None:
    """Locate wild_encounters.json if present; None means standalone mode."""
    if explicit is not None:
        return explicit if explicit.is_file() else None
    candidates = [
        REPO_ROOT / "src" / "data" / "wild_encounters.json",
        SCRIPT_DIR / "wild_encounters.json",
        SCRIPT_DIR / "src" / "data" / "wild_encounters.json",
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


def list_land_maps(
    encounters_path: Path,
    version: str | None = None,
) -> list[tuple[str, str]]:
    """Return (map_constant_without_MAP_, base_label) for maps with land_mons."""
    data = json.loads(encounters_path.read_text())
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    for group in data["wild_encounter_groups"]:
        for enc in group.get("encounters", []):
            land = enc.get("land_mons")
            if not land:
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
    """Load land_mons slots for a map from wild_encounters.json."""
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
        raise SystemExit(
            f"No land encounters found for {map_key}. Try --list-maps or a built-in map."
        )
    if len(matches) > 1 and not version:
        labels = ", ".join(label for label, _ in matches)
        raise SystemExit(
            f"Multiple versions for {map_key}: {labels}. Pass --version firered|leafgreen."
        )
    return matches[0]


def resolve_area(
    map_name: str,
    encounters_path: Path | None,
    version: str,
    prefer_builtin: bool = False,
) -> tuple[str, list[Slot]]:
    """Resolve built-in tables first when requested / when JSON is missing."""
    key = map_name.upper()
    if key.startswith("MAP_"):
        key = key[4:]

    if prefer_builtin or encounters_path is None:
        if key in BUILTIN_AREAS:
            return BUILTIN_AREAS[key]
        if encounters_path is None:
            builtin = ", ".join(sorted(BUILTIN_AREAS))
            raise SystemExit(
                f"No wild_encounters.json found, and {key!r} is not built in.\n"
                f"Built-in maps: {builtin}\n"
                "Copy wild_encounters.json next to this script to use other maps."
            )

    if encounters_path is not None:
        try:
            return load_map_land_slots(encounters_path, key, version)
        except SystemExit:
            if key in BUILTIN_AREAS:
                return BUILTIN_AREAS[key]
            raise

    return BUILTIN_AREAS[key]


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
            "Note: encounter purity and raw target rolls can peak at different leads; "
            "hunters usually optimize the conditional rate when walking is cheap."
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
    max_wild = max(max(slot.min_level, slot.max_level) for slot in slots)
    min_wild = min(min(slot.min_level, slot.max_level) for slot in slots)
    hi = max_lead if max_lead is not None else max_wild + 1
    lead_levels = range(min_lead, hi + 1)

    print(f"Source: {label}")
    print(f"Wild level range: {min_wild}-{max_wild}")
    print("Mechanics: Gen 3 Repel (block if wild_level < lead_level)")
    print()
    if show_slots:
        print(format_slot_summary(slots))
        print()

    results = analyze(slots, target, lead_levels)
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


def interactive_menu(encounters_path: Path | None, version: str) -> int:
    has_json = encounters_path is not None
    print("Gen 3 Repel filter calculator")
    print("Standalone mode." if not has_json else f"JSON: {encounters_path}")
    print()
    while True:
        print("Choose an area:")
        print("  1) Rock Tunnel B1F  (Onix)  [built-in, exact slots]")
        print("  2) Rock Tunnel 1F   (Onix)  [built-in, exact slots]")
        print("  3) Rock Tunnel aggregate table (approx.)")
        if has_json:
            print("  4) Other map from wild_encounters.json")
            print("  5) List all maps")
        else:
            print("  4) Other map  (needs wild_encounters.json — not found)")
            print("  5) List maps  (needs wild_encounters.json — not found)")
        print("  6) Custom target on a built-in map")
        print("  0) Quit")
        choice = input("> ").strip()

        if choice in ("0", "q", "quit", "exit"):
            return 0
        if choice == "1":
            label, slots = BUILTIN_AREAS["ROCK_TUNNEL_B1F"]
            run_analysis(label, slots, "ONIX")
        elif choice == "2":
            label, slots = BUILTIN_AREAS["ROCK_TUNNEL_1F"]
            run_analysis(label, slots, "ONIX")
        elif choice == "3":
            label, slots = BUILTIN_AREAS["USER_TABLE"]
            run_analysis(label, slots, "ONIX")
        elif choice == "4":
            if not has_json:
                print(
                    "Copy wild_encounters.json next to this script to unlock other maps.\n"
                )
                continue
            map_name = input("Map name (e.g. VICTORY_ROAD_1F): ").strip()
            if not map_name:
                continue
            target = input("Target species [ONIX]: ").strip() or "ONIX"
            label, slots = resolve_area(map_name, encounters_path, version)
            run_analysis(label, slots, target)
        elif choice == "5":
            if not has_json:
                print("Built-in maps (no JSON needed):")
                for key, (label, _) in sorted(BUILTIN_AREAS.items()):
                    print(f"  {key}  ({label})")
                print()
                continue
            rows = list_land_maps(encounters_path, version)
            print(f"Maps with land encounters ({version}, {len(rows)}):")
            for short, label in rows:
                print(f"  {short}  ({label})")
            print()
        elif choice == "6":
            print("Built-in maps:", ", ".join(sorted(BUILTIN_AREAS)))
            map_name = input("Map key [ROCK_TUNNEL_B1F]: ").strip() or "ROCK_TUNNEL_B1F"
            target = input("Target species [ONIX]: ").strip() or "ONIX"
            if map_name.upper() not in BUILTIN_AREAS:
                print(f"Unknown built-in map {map_name!r}\n")
                continue
            label, slots = BUILTIN_AREAS[map_name.upper()]
            run_analysis(label, slots, target)
        else:
            print("Invalid choice.\n")
            continue
        print()
        again = input("Run another? [Y/n] ").strip().lower()
        if again in ("n", "no"):
            return 0
        print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find the best Gen 3 Repel lead level for a target wild Pokémon."
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--map",
        default=None,
        help="Map constant, e.g. ROCK_TUNNEL_B1F. Built-ins work without JSON.",
    )
    src.add_argument(
        "--user-table",
        action="store_true",
        help="Use the aggregated Rock Tunnel table from the request (approx.)",
    )
    src.add_argument(
        "--list-maps",
        action="store_true",
        help="Print map names (built-ins always; all maps if JSON is present)",
    )
    src.add_argument(
        "--interactive",
        action="store_true",
        help="Menu mode (default when no args — useful in Pythonista)",
    )
    p.add_argument(
        "--version",
        choices=("firered", "leafgreen"),
        default="firered",
        help="Game version when loading from wild_encounters.json (default: firered)",
    )
    p.add_argument(
        "--encounters",
        type=Path,
        default=None,
        help="Path to wild_encounters.json (optional)",
    )
    p.add_argument(
        "--target",
        default="ONIX",
        help="Target species (default: ONIX)",
    )
    p.add_argument(
        "--min-lead",
        type=int,
        default=1,
        help="Minimum lead level to evaluate (default: 1)",
    )
    p.add_argument(
        "--max-lead",
        type=int,
        default=None,
        help="Maximum lead level to evaluate (default: highest wild level + 1)",
    )
    p.add_argument(
        "--show-slots",
        action="store_true",
        help="Print the slot table used",
    )
    p.add_argument(
        "--breakdown",
        type=int,
        metavar="LEAD",
        help="Also print species mix for a specific lead level",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    # Pythonista / double-click: no useful argv beyond the script name.
    if argv is None:
        argv = sys.argv[1:]

    # No flags -> interactive (also --interactive).
    if not argv or argv == ["--interactive"]:
        encounters = find_encounters_json(None)
        return interactive_menu(encounters, "firered")

    args = parse_args(argv)
    encounters = find_encounters_json(args.encounters)

    if args.interactive:
        return interactive_menu(encounters, args.version)

    if args.list_maps:
        print("Built-in maps (no JSON needed):")
        for key, (label, _) in sorted(BUILTIN_AREAS.items()):
            print(f"  {key}  ({label})")
        if encounters is None:
            print("\nNo wild_encounters.json found; other maps unavailable.")
            return 0
        rows = list_land_maps(encounters, args.version)
        print(f"\nMaps from JSON ({args.version}, {len(rows)}):")
        for short, label in rows:
            print(f"  {short}  ({label})")
        return 0

    if args.user_table:
        label, slots = BUILTIN_AREAS["USER_TABLE"]
    else:
        map_name = args.map or "ROCK_TUNNEL_B1F"
        label, slots = resolve_area(map_name, encounters, args.version)

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
