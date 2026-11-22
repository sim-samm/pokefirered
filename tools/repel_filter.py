#!/usr/bin/env python3
"""
Gen 3 Repel filter calculator (FireRed / LeafGreen).

With a Repel active, a wild encounter is allowed only when
wild_level >= lead_level (see IsWildLevelAllowedByRepel in src/wild_encounter.c).
Blocked rolls cancel the encounter; they do not re-roll the slot.

This tool reports, for each lead level, the conditional probability that an
encounter which DOES occur is the target species, plus the relative absolute
weight of target encounters (useful for steps-per-encounter estimates).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


# Land slot weights from wild_encounters.json field encounter_rates (sum = 100).
LAND_SLOT_RATES = (20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENCOUNTERS = REPO_ROOT / "src" / "data" / "wild_encounters.json"


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


def _land_rates_for_group(group: dict) -> tuple[float, ...]:
    for field in group.get("fields", []):
        if field.get("type") == "land_mons":
            return tuple(field["encounter_rates"])
    return LAND_SLOT_RATES


def _version_matches(label: str, version: str | None) -> bool:
    if not version:
        return True
    # Labels look like sRockTunnelB1F_FireRed / _LeafGreen
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
            short = map_name.removeprefix("MAP_")
            # Prefer first match per short name (FireRed before LeafGreen when unfiltered).
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
        available = ", ".join(name for name, _ in list_land_maps(encounters_path, version)[:12])
        hint = f" Try --list-maps. Examples: {available}…" if available else " Try --list-maps."
        raise SystemExit(f"No land encounters found for {map_key}.{hint}")
    if len(matches) > 1 and not version:
        labels = ", ".join(label for label, _ in matches)
        raise SystemExit(
            f"Multiple versions for {map_key}: {labels}. Pass --version firered|leafgreen."
        )
    return matches[0]


def slots_from_manual_table(rows: list[tuple[str, int, int, float]]) -> list[Slot]:
    """
    Build slots from aggregated Bulbapedia-style rows:
    (species, min_level, max_level, rate_percent).

    Level mass is spread uniformly across the inclusive level range.
    Prefer --map with real JSON slots when accuracy matters.
    """
    return [
        Slot(species=normalize_species(sp), min_level=lo, max_level=hi, rate=rate)
        for sp, lo, hi, rate in rows
    ]


# User-provided Rock Tunnel table (Bulbapedia-style aggregates for FR/LG).
# Matches Rock Tunnel B1F totals; prefer JSON slots for exact answers.
ROCK_TUNNEL_USER_TABLE = [
    ("Zubat", 15, 16, 30.0),
    ("Mankey", 16, 17, 15.0),
    ("Machop", 17, 17, 10.0),
    ("Geodude", 15, 17, 35.0),
    ("Onix", 13, 17, 10.0),
]


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
    target_name = normalize_species(target).removeprefix("SPECIES_").title()
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
    # Call out hunts where filtering never beats the unfiltered rate (e.g. Rock Tunnel Onix).
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
        name = sp.removeprefix("SPECIES_").replace("_", " ").title()
        mark = "  <-- target" if sp == target else ""
        lines.append(f"  {100.0 * w / total:6.2f}%  {name}{mark}")
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Find the best Gen 3 Repel lead level for a target wild Pokémon."
    )
    src = p.add_mutually_exclusive_group()
    src.add_argument(
        "--map",
        default="ROCK_TUNNEL_B1F",
        help="Map constant to analyze, e.g. ROCK_TUNNEL_B1F (default). Use --list-maps for names.",
    )
    src.add_argument(
        "--user-table",
        action="store_true",
        help="Use the aggregated Rock Tunnel table from the request (approx.)",
    )
    src.add_argument(
        "--list-maps",
        action="store_true",
        help="Print all map names that have land encounters, then exit",
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
        default=DEFAULT_ENCOUNTERS,
        help="Path to wild_encounters.json",
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
    args = parse_args(argv)

    if args.list_maps:
        rows = list_land_maps(args.encounters, args.version)
        print(f"Maps with land encounters ({args.version}, {len(rows)}):")
        for short, label in rows:
            print(f"  {short}  ({label})")
        return 0

    if args.user_table:
        label = "user-provided Rock Tunnel aggregate table"
        slots = slots_from_manual_table(ROCK_TUNNEL_USER_TABLE)
    else:
        label, slots = load_map_land_slots(args.encounters, args.map, args.version)

    max_wild = max(max(slot.min_level, slot.max_level) for slot in slots)
    min_wild = min(min(slot.min_level, slot.max_level) for slot in slots)
    max_lead = args.max_lead if args.max_lead is not None else max_wild + 1
    min_lead = args.min_lead
    lead_levels = range(min_lead, max_lead + 1)

    print(f"Source: {label}")
    print(f"Wild level range: {min_wild}-{max_wild}")
    print(f"Mechanics: Gen 3 Repel (block if wild_level < lead_level)")
    print()
    if args.show_slots:
        print(format_slot_summary(slots))
        print()

    results = analyze(slots, args.target, lead_levels)
    # Trim leading rows that are identical to "no filter" for readability:
    # still print from min_wild-1 upward if that range was requested.
    interesting = [r for r in results if r.lead_level >= min_wild - 1]
    print(format_results(args.target, interesting if interesting else results))

    if args.breakdown is not None:
        print()
        print(species_breakdown(slots, args.breakdown, args.target))

    # Highlight an optimal lead (highest lead among ties — the practical Repel level).
    valid = [r for r in results if r.conditional_pct is not None]
    if valid:
        best_val = max(r.conditional_pct for r in valid)
        best = max(
            (r for r in valid if r.conditional_pct == best_val),
            key=lambda r: r.lead_level,
        )
        print()
        print(species_breakdown(slots, best.lead_level, args.target))

    return 0


if __name__ == "__main__":
    sys.exit(main())
