#!/usr/bin/env python3
"""
Strict verification: tools/repel_calc/encounters.json must match pret source.

Source of truth:
  src/data/wild_encounters.json
  (slot weights from that file's fields[].encounter_rates, which generate
   ENCOUNTER_CHANCE_* macros used by src/wild_encounter.c)

This script does NOT import export_encounters.py — it re-reads pret JSON
independently so a buggy exporter cannot grade its own homework.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_PRET = REPO_ROOT / "src" / "data" / "wild_encounters.json"
DEFAULT_PACK = HERE / "encounters.json"

METHOD_FIELD = {
    "land": "land_mons",
    "water": "water_mons",
    "rock_smash": "rock_smash_mons",
}


def strip_species(species: str) -> str:
    return species[8:] if species.startswith("SPECIES_") else species


def load_pret_truth(pret_path: Path) -> tuple[dict, dict]:
    pret = json.loads(pret_path.read_text())
    rates: dict[str, list[int]] = {}
    for group in pret["wild_encounter_groups"]:
        for field in group.get("fields", []):
            rates[field["type"]] = list(field["encounter_rates"])

    truth: dict[tuple[str, str, str], list[tuple[str, int, int, int]]] = {}
    for group in pret["wild_encounter_groups"]:
        for enc in group.get("encounters", []):
            label = enc.get("base_label", "")
            if "FireRed" in label:
                ver = "firered"
            elif "LeafGreen" in label:
                ver = "leafgreen"
            else:
                continue
            map_id = enc["map"][4:] if enc["map"].startswith("MAP_") else enc["map"]
            for method, field_name in METHOD_FIELD.items():
                block = enc.get(field_name)
                if not block:
                    continue
                slot_rates = rates[field_name]
                mons = block["mons"]
                if len(mons) != len(slot_rates):
                    raise SystemExit(
                        f"pret {map_id}/{ver}/{method}: {len(mons)} mons vs "
                        f"{len(slot_rates)} rates"
                    )
                slots = []
                for i, mon in enumerate(mons):
                    slots.append(
                        (
                            strip_species(mon["species"]),
                            int(mon["min_level"]),
                            int(mon["max_level"]),
                            int(slot_rates[i]),
                        )
                    )
                truth[(map_id, ver, method)] = slots
    return rates, truth


def load_package_slots(
    pack_path: Path,
) -> tuple[dict, dict[tuple[str, str, str], list[tuple[str, int, int, int]]]]:
    pack = json.loads(pack_path.read_text())
    rates = pack["slot_rates"]
    got: dict[tuple[str, str, str], list[tuple[str, int, int, int]]] = {}
    for area in pack["areas"]:
        map_id = area["id"]
        if "encounters" in area:
            versions = [("firered", area["encounters"]), ("leafgreen", area["encounters"])]
        else:
            versions = [(v, area[v]) for v in ("firered", "leafgreen") if v in area]
        for ver, block in versions:
            for method in METHOD_FIELD:
                rows = block.get(method)
                if not rows:
                    continue
                slot_rates = rates[method]
                if len(rows) != len(slot_rates):
                    raise SystemExit(
                        f"package {map_id}/{ver}/{method}: {len(rows)} rows vs "
                        f"{len(slot_rates)} rates"
                    )
                got[(map_id, ver, method)] = [
                    (sp, int(lo), int(hi), int(slot_rates[i]))
                    for i, (sp, lo, hi) in enumerate(rows)
                ]
    return rates, got


def species_aggregate(
    slots: list[tuple[str, int, int, int]], species: str
) -> tuple[int, list[int]]:
    species = species.upper()
    total = 0
    levels: set[int] = set()
    for sp, lo, hi, rate in slots:
        if sp.upper() != species:
            continue
        total += rate
        levels.update(range(lo, hi + 1))
    return total, sorted(levels)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pret", type=Path, default=DEFAULT_PRET)
    p.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    p.add_argument(
        "--check-growlithe",
        action="store_true",
        help="Print pret Growlithe aggregates for Route 7/8 (FireRed)",
    )
    args = p.parse_args()

    if not args.pret.is_file():
        print(f"FAIL: missing pret source {args.pret}", file=sys.stderr)
        return 2
    if not args.pack.is_file():
        print(f"FAIL: missing package {args.pack}", file=sys.stderr)
        return 2

    pret_rates, truth = load_pret_truth(args.pret)
    pack_rates, got = load_package_slots(args.pack)

    errors: list[str] = []
    for method, field_name in METHOD_FIELD.items():
        if pack_rates.get(method) != pret_rates.get(field_name):
            errors.append(
                f"slot_rates[{method}] {pack_rates.get(method)} != pret "
                f"{field_name} {pret_rates.get(field_name)}"
            )

    for key, exp in sorted(truth.items()):
        if key not in got:
            errors.append(f"missing in package: {key}")
            continue
        if got[key] != exp:
            errors.append(f"slot mismatch {key}\n  pret: {exp}\n  pack: {got[key]}")
        del got[key]
    for key in sorted(got):
        errors.append(f"extra in package (not in pret land/water/rock): {key}")

    if args.check_growlithe:
        print("pret FireRed Growlithe (source of truth):")
        for map_id in ("ROUTE7", "ROUTE8"):
            slots = truth[(map_id, "firered", "land")]
            total, levels = species_aggregate(slots, "GROWLITHE")
            print(f"  {map_id}: {total}% at levels {levels}")
            for sp, lo, hi, rate in slots:
                if sp == "GROWLITHE":
                    print(f"    slot {rate}% Lv{lo}" + (f"-{hi}" if hi != lo else ""))

    if errors:
        print(f"FAIL: {len(errors)} disagreement(s) with pret source")
        for err in errors[:30]:
            print(err)
        if len(errors) > 30:
            print(f"... and {len(errors) - 30} more")
        return 1

    print(
        f"OK: {args.pack.name} matches pret {args.pret} "
        f"({len(truth)} versioned method tables)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
