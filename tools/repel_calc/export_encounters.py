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
DEFAULT_ABILITIES_OUT = HERE / "species_abilities.json"
SPECIES_INFO = REPO_ROOT / "src" / "data" / "pokemon" / "species_info.h"
ABILITY_NAMES = REPO_ROOT / "src" / "data" / "text" / "abilities.h"


def pretty_map(map_const: str) -> str:
    """Human label from MAP_* constant, e.g. MAP_ROUTE7 -> 'Route 7'."""
    import re

    name = map_const[4:] if map_const.startswith("MAP_") else map_const
    parts = []
    for part in name.split("_"):
        # ROUTE7 -> Route 7; leave B1F / 1F-style tokens alone.
        m = re.match(r"^([A-Za-z]+)(\d+)$", part)
        if m:
            parts.append(f"{m.group(1).title()} {m.group(2)}")
        else:
            parts.append(part.title() if part.isalpha() else part)
    return " ".join(parts)


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


def export_abilities(species_info: Path, ability_names: Path, out_path: Path) -> None:
    """Export FR/LG ability names per species from pret headers."""
    import re

    name_map: dict[str, str | None] = {}
    for m in re.finditer(
        r"\[(ABILITY_\w+)\]\s*=\s*_\(\"([^\"]*)\"\)", ability_names.read_text()
    ):
        raw = m.group(2)
        pretty = None if set(raw) <= {"-"} else " ".join(w.capitalize() for w in raw.split())
        name_map[m.group(1)] = pretty

    info = species_info.read_text()
    species: dict[str, dict] = {}
    for m in re.finditer(r"\[SPECIES_(\w+)\]", info):
        sp = m.group(1)
        window = info[m.start() : m.start() + 800]
        am = re.search(
            r"\.abilities\s*=\s*\{\s*(ABILITY_\w+)\s*,\s*(ABILITY_\w+)\s*\}", window
        )
        if not am:
            continue
        a0, a1 = am.group(1), am.group(2)
        n0, n1 = name_map.get(a0), name_map.get(a1)
        if n0 is None:
            continue
        dual = a1 != "ABILITY_NONE" and n1 is not None and a0 != a1
        species[sp] = {
            "slot0": n0,
            "slot1": n1 if dual else None,
            "dual": dual,
        }

    payload = {
        "source": "src/data/pokemon/species_info.h + src/data/text/abilities.h",
        "rule": "if abilities[1] nonzero: abilityNum = personality & 1; else always slot0",
        "species": species,
    }
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    print(f"Wrote {out_path} ({out_path.stat().st_size} bytes, {len(species)} species)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--src", type=Path, default=DEFAULT_SRC)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--abilities-out", type=Path, default=DEFAULT_ABILITIES_OUT)
    args = p.parse_args()
    if not args.src.is_file():
        raise SystemExit(f"Missing source encounters: {args.src}")
    export(args.src, args.out)
    if SPECIES_INFO.is_file() and ABILITY_NAMES.is_file():
        export_abilities(SPECIES_INFO, ABILITY_NAMES, args.abilities_out)
    else:
        print("Skip species_abilities.json (headers not found)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
