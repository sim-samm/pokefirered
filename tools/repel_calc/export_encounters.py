#!/usr/bin/env python3
"""Rebuild encounters.json from pokefirered src/data/wild_encounters.json."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
DEFAULT_SRC = REPO_ROOT / "src" / "data" / "wild_encounters.json"
DEFAULT_OUT = HERE / "encounters.json"


def pretty_map(map_const: str) -> str:
    name = map_const[4:] if map_const.startswith("MAP_") else map_const
    return name.replace("_", " ").title()


def strip_species(species: str) -> str:
    return species[8:] if species.startswith("SPECIES_") else species


def pack_mons(mons: list[dict]) -> list[list]:
    return [[strip_species(m["species"]), m["min_level"], m["max_level"]] for m in mons]


def export(src_path: Path, out_path: Path) -> None:
    src = json.loads(src_path.read_text())
    land_rates = water_rates = rock_rates = None
    for group in src["wild_encounter_groups"]:
        for field in group.get("fields", []):
            kind = field.get("type")
            if kind == "land_mons" and land_rates is None:
                land_rates = field["encounter_rates"]
            elif kind == "water_mons" and water_rates is None:
                water_rates = field["encounter_rates"]
            elif kind == "rock_smash_mons" and rock_rates is None:
                rock_rates = field["encounter_rates"]

    areas: dict[str, dict] = {}
    for group in src["wild_encounter_groups"]:
        for enc in group.get("encounters", []):
            label = enc.get("base_label", "")
            if "FireRed" in label:
                ver = "firered"
            elif "LeafGreen" in label:
                ver = "leafgreen"
            else:
                continue
            map_const = enc["map"]
            map_id = map_const[4:] if map_const.startswith("MAP_") else map_const
            entry = areas.setdefault(
                map_id, {"id": map_id, "name": pretty_map(map_const), "versions": {}}
            )
            block: dict = {}
            if enc.get("land_mons"):
                block["land"] = pack_mons(enc["land_mons"]["mons"])
            if enc.get("water_mons"):
                block["water"] = pack_mons(enc["water_mons"]["mons"])
            if enc.get("rock_smash_mons"):
                block["rock_smash"] = pack_mons(enc["rock_smash_mons"]["mons"])
            if block:
                entry["versions"][ver] = block

    collapsed = []
    for map_id, entry in sorted(areas.items()):
        vers = entry["versions"]
        fr = vers.get("firered")
        lg = vers.get("leafgreen")
        out = {"id": entry["id"], "name": entry["name"]}
        if fr and lg and fr == lg:
            out["encounters"] = fr
        else:
            if fr:
                out["firered"] = fr
            if lg:
                out["leafgreen"] = lg
        collapsed.append(out)

    payload = {
        "game": "pokemon-firered-leafgreen",
        "source": "src/data/wild_encounters.json",
        "repel_rule": "wild_level >= lead_level",
        "slot_rates": {
            "land": land_rates,
            "water": water_rates,
            "rock_smash": rock_rates,
        },
        "areas": collapsed,
    }
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes, {len(collapsed)} areas)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=DEFAULT_SRC)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args()
    if not args.src.is_file():
        raise SystemExit(f"Missing source encounters: {args.src}")
    export(args.src, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
