#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export EV training data from pokefirered source files.

Reads species_info.h for EV yields and encounters.json for wild spots.
Outputs ev_data.json for use by ev_trainer.py and ev_trainer_gui.py.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
SPECIES_INFO = REPO_ROOT / "src" / "data" / "pokemon" / "species_info.h"
ENCOUNTERS_JSON = HERE.parent / "repel_calc" / "encounters.json"
OUTPUT_FILE = HERE / "ev_data.json"
JSON_ENCODING = "utf-8"

STATS = ["HP", "Attack", "Defense", "Speed", "SpAtk", "SpDef"]
EV_FIELD_MAP = {
    "evYield_HP": "HP",
    "evYield_Attack": "Attack",
    "evYield_Defense": "Defense",
    "evYield_Speed": "Speed",
    "evYield_SpAttack": "SpAtk",
    "evYield_SpDefense": "SpDef",
}

LAND_SLOT_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
WATER_SLOT_RATES = [60, 30, 5, 4, 1]


def parse_species_evs(path: Path) -> dict[str, dict[str, int]]:
    """Parse species_info.h for EV yields per species."""
    if not path.is_file():
        print(f"Warning: {path} not found", file=sys.stderr)
        return {}

    text = path.read_text(encoding="utf-8")
    species_evs: dict[str, dict[str, int]] = {}
    current_species = None
    current_evs: dict[str, int] = {}

    species_pattern = re.compile(r'\[SPECIES_(\w+)\]\s*=')
    ev_pattern = re.compile(r'\.evYield_(\w+)\s*=\s*(\d+)')

    for line in text.splitlines():
        species_match = species_pattern.search(line)
        if species_match:
            if current_species and any(v > 0 for v in current_evs.values()):
                species_evs[current_species] = dict(current_evs)
            current_species = species_match.group(1)
            current_evs = {stat: 0 for stat in STATS}

        if current_species:
            ev_match = ev_pattern.search(line)
            if ev_match:
                field = f"evYield_{ev_match.group(1)}"
                value = int(ev_match.group(2))
                stat = EV_FIELD_MAP.get(field)
                if stat:
                    current_evs[stat] = value

    if current_species and any(v > 0 for v in current_evs.values()):
        species_evs[current_species] = dict(current_evs)

    return species_evs


def load_encounters(path: Path) -> dict:
    """Load encounters.json from repel_calc."""
    if not path.is_file():
        print(f"Warning: {path} not found", file=sys.stderr)
        return {"areas": []}
    return json.loads(path.read_text(encoding=JSON_ENCODING))


def normalize_species(name: str) -> str:
    name = name.strip().upper()
    if name.startswith("SPECIES_"):
        name = name[8:]
    return name


def build_wild_spots(encounters: dict, species_evs: dict) -> list[dict]:
    """Build wild spot data with EV info."""
    spots = []

    for area in encounters.get("areas", []):
        area_id = area.get("id", "")
        area_name = area.get("name", area_id)

        for version in ["firered", "leafgreen", "encounters"]:
            block = area.get(version) if version != "encounters" else area.get("encounters")
            if not block:
                continue

            ver_label = "both" if version == "encounters" else version

            for method, slot_rates in [("land", LAND_SLOT_RATES), ("water", WATER_SLOT_RATES)]:
                slots = block.get(method)
                if not slots:
                    continue

                pokemon_data: dict[str, dict] = {}

                for i, (species, min_lv, max_lv) in enumerate(slots):
                    sp_key = normalize_species(species)
                    rate = slot_rates[i] if i < len(slot_rates) else 0

                    if sp_key not in pokemon_data:
                        pokemon_data[sp_key] = {
                            "rate": 0.0,
                            "levels": (min_lv, max_lv),
                            "evs": species_evs.get(sp_key, {}),
                        }

                    pokemon_data[sp_key]["rate"] += rate
                    existing_lo, existing_hi = pokemon_data[sp_key]["levels"]
                    pokemon_data[sp_key]["levels"] = (
                        min(existing_lo, min_lv),
                        max(existing_hi, max_lv),
                    )

                ev_totals: dict[str, float] = {stat: 0.0 for stat in STATS}
                for sp_key, data in pokemon_data.items():
                    rate_pct = data["rate"]
                    for stat, ev in data.get("evs", {}).items():
                        ev_totals[stat] += (rate_pct / 100.0) * ev

                if not any(v > 0 for v in ev_totals.values()):
                    continue

                spots.append({
                    "location": area_name,
                    "location_id": area_id,
                    "method": method,
                    "version": ver_label,
                    "pokemon": pokemon_data,
                    "ev_rates": {k: round(v, 3) for k, v in ev_totals.items() if v > 0},
                })

    return spots


def find_best_spots(spots: list[dict]) -> dict[str, list[dict]]:
    """Find best spots for each stat."""
    best: dict[str, list[dict]] = {stat: [] for stat in STATS}

    for spot in spots:
        ev_rates = spot.get("ev_rates", {})
        for stat in STATS:
            rate = ev_rates.get(stat, 0)
            if rate > 0:
                purity = calculate_purity(spot, stat)
                best[stat].append({
                    "location": spot["location"],
                    "location_id": spot["location_id"],
                    "method": spot["method"],
                    "version": spot["version"],
                    "ev_rate": rate,
                    "purity": round(purity, 1),
                    "pokemon": get_stat_pokemon(spot, stat),
                })

    for stat in STATS:
        best[stat] = sorted(best[stat], key=lambda x: (-x["purity"], -x["ev_rate"]))[:10]

    return best


def calculate_purity(spot: dict, target_stat: str) -> float:
    """Calculate what % of encounters yield only the target stat."""
    pokemon = spot.get("pokemon", {})
    target_rate = 0.0
    total_rate = 0.0

    for sp_key, data in pokemon.items():
        rate = data.get("rate", 0)
        evs = data.get("evs", {})
        total_rate += rate

        target_ev = evs.get(target_stat, 0)
        other_evs = sum(evs.get(s, 0) for s in STATS if s != target_stat)

        if target_ev > 0 and other_evs == 0:
            target_rate += rate

    if total_rate == 0:
        return 0.0
    return 100.0 * target_rate / total_rate


def get_stat_pokemon(spot: dict, target_stat: str) -> list[dict]:
    """Get pokemon in spot that yield the target stat."""
    pokemon = spot.get("pokemon", {})
    result = []

    for sp_key, data in pokemon.items():
        evs = data.get("evs", {})
        ev_val = evs.get(target_stat, 0)
        if ev_val > 0:
            lo, hi = data.get("levels", (1, 1))
            result.append({
                "species": sp_key,
                "ev": ev_val,
                "rate": data.get("rate", 0),
                "levels": f"{lo}-{hi}" if lo != hi else str(lo),
            })

    return sorted(result, key=lambda x: (-x["rate"], x["species"]))


def main():
    print("Parsing species EV yields...")
    species_evs = parse_species_evs(SPECIES_INFO)
    print(f"  Found {len(species_evs)} species with EV yields")

    print("Loading encounter data...")
    encounters = load_encounters(ENCOUNTERS_JSON)
    print(f"  Found {len(encounters.get('areas', []))} areas")

    print("Building wild spot data...")
    wild_spots = build_wild_spots(encounters, species_evs)
    print(f"  Generated {len(wild_spots)} wild training spots")

    print("Finding best spots per stat...")
    best_spots = find_best_spots(wild_spots)
    for stat in STATS:
        top = best_spots[stat][0] if best_spots[stat] else None
        if top:
            print(f"  {stat}: {top['location']} ({top['purity']}% pure, {top['ev_rate']} EV/battle)")

    output = {
        "source": "pokefirered decomp",
        "species_evs": species_evs,
        "wild_spots": wild_spots,
        "best_spots": best_spots,
    }

    print(f"Writing {OUTPUT_FILE.name}...")
    OUTPUT_FILE.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding=JSON_ENCODING,
    )
    print("Done!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
