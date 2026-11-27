#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EV Training helper for FireRed/LeafGreen.

Core logic module - no ui imports. Can be used standalone or with ev_trainer_gui.py.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EV_DATA_FILE = HERE / "ev_data.json"
TRAINER_SPOTS_FILE = HERE / "trainer_spots.json"
JSON_ENCODING = "utf-8"

STATS = ("HP", "Attack", "Defense", "SpAtk", "SpDef", "Speed")
STAT_KEYS = {
    "HP": "HP", "hp": "HP",
    "Attack": "Attack", "Atk": "Attack", "attack": "Attack", "atk": "Attack",
    "Defense": "Defense", "Def": "Defense", "defense": "Defense", "def": "Defense",
    "SpAtk": "SpAtk", "Sp. Atk": "SpAtk", "SpA": "SpAtk", "spatk": "SpAtk",
    "SpDef": "SpDef", "Sp. Def": "SpDef", "SpD": "SpDef", "spdef": "SpDef",
    "Speed": "Speed", "Spe": "Speed", "speed": "Speed", "spe": "Speed",
}

MAX_TOTAL_EVS = 510
MAX_PER_STAT_EVS = 255
VITAMIN_CAP = 100
VITAMIN_EV = 10
VITAMIN_PRICE = 9800

LAND_SLOT_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
WATER_SLOT_RATES = [60, 30, 5, 4, 1]

TRAINER_MONEY_TABLE = {
    "LEADER": 25, "ELITE_FOUR": 25, "CHAMPION": 25,
    "YOUNGSTER": 4, "BUG_CATCHER": 3, "HIKER": 9, "BIRD_KEEPER": 6,
    "PICNICKER": 5, "SUPER_NERD": 6, "FISHERMAN": 9, "TEAM_ROCKET": 8,
    "LASS": 4, "BEAUTY": 18, "BLACK_BELT": 6, "CUE_BALL": 6,
    "CHANNELER": 8, "ROCKER": 6, "GENTLEMAN": 18, "BURGLAR": 22,
    "SWIMMER_M": 1, "SWIMMER_F": 1, "ENGINEER": 12, "JUGGLER": 10,
    "SAILOR": 8, "COOLTRAINER": 9, "POKEMANIAC": 12, "TAMER": 10,
    "CAMPER": 5, "PSYCHIC": 5, "BIKER": 5, "GAMER": 18,
    "SCIENTIST": 12, "CRUSH_GIRL": 6, "TUBER": 1, "PKMN_BREEDER": 7,
    "PKMN_RANGER": 9, "AROMA_LADY": 7, "RUIN_MANIAC": 12, "LADY": 50,
    "PAINTER": 4, "TWINS": 3, "YOUNG_COUPLE": 7, "SIS_AND_BRO": 1,
    "COOL_COUPLE": 6, "CRUSH_KIN": 6, "RICH_BOY": 50,
}


def _read_utf8(path: Path) -> str:
    return path.read_text(encoding=JSON_ENCODING)


def normalize_stat(stat: str) -> str:
    return STAT_KEYS.get(stat, stat)


@dataclass
class Pokemon:
    name: str
    target_evs: dict[str, int] = field(default_factory=dict)
    current_evs: dict[str, int] = field(default_factory=dict)
    using_macho_brace: bool = False

    def __post_init__(self):
        for stat in STATS:
            self.target_evs.setdefault(stat, 0)
            self.current_evs.setdefault(stat, 0)

    def remaining_evs(self, stat: str) -> int:
        stat = normalize_stat(stat)
        return max(0, self.target_evs.get(stat, 0) - self.current_evs.get(stat, 0))

    def total_remaining(self) -> int:
        return sum(self.remaining_evs(s) for s in STATS)

    def total_current(self) -> int:
        return sum(self.current_evs.get(s, 0) for s in STATS)

    def total_target(self) -> int:
        return sum(self.target_evs.get(s, 0) for s in STATS)

    def add_evs(self, stat: str, amount: int) -> int:
        stat = normalize_stat(stat)
        current = self.current_evs.get(stat, 0)
        total = self.total_current()
        per_stat_cap = min(MAX_PER_STAT_EVS, self.target_evs.get(stat, MAX_PER_STAT_EVS))
        room_stat = max(0, per_stat_cap - current)
        room_total = max(0, MAX_TOTAL_EVS - total)
        actual = min(amount, room_stat, room_total)
        self.current_evs[stat] = current + actual
        return actual

    def vitamins_usable(self, stat: str) -> int:
        stat = normalize_stat(stat)
        current = self.current_evs.get(stat, 0)
        if current >= VITAMIN_CAP:
            return 0
        room = VITAMIN_CAP - current
        return room // VITAMIN_EV

    def use_vitamin(self, stat: str) -> bool:
        if self.vitamins_usable(stat) <= 0:
            return False
        self.add_evs(stat, VITAMIN_EV)
        return True

    def is_complete(self) -> bool:
        return self.total_remaining() == 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "target_evs": dict(self.target_evs),
            "current_evs": dict(self.current_evs),
            "using_macho_brace": self.using_macho_brace,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pokemon":
        return cls(
            name=d.get("name", ""),
            target_evs=d.get("target_evs", {}),
            current_evs=d.get("current_evs", {}),
            using_macho_brace=d.get("using_macho_brace", False),
        )


@dataclass
class Party:
    pokemon: list[Pokemon] = field(default_factory=list)
    money: int = 0
    exp_share_holder: int | None = None
    amulet_coin_holder: bool = False

    def add_pokemon(self, mon: Pokemon) -> bool:
        if len(self.pokemon) >= 6:
            return False
        self.pokemon.append(mon)
        return True

    def remove_pokemon(self, index: int) -> bool:
        if 0 <= index < len(self.pokemon):
            self.pokemon.pop(index)
            if self.exp_share_holder == index:
                self.exp_share_holder = None
            elif self.exp_share_holder is not None and self.exp_share_holder > index:
                self.exp_share_holder -= 1
            return True
        return False

    def add_battle_money(self, trainer_class: str, last_mon_level: int, is_double: bool = False) -> int:
        multiplier = TRAINER_MONEY_TABLE.get(trainer_class.upper(), 4)
        base = 4 * last_mon_level * multiplier
        if is_double:
            base *= 2
        if self.amulet_coin_holder:
            base *= 2
        self.money += base
        return base

    def can_afford_vitamin(self) -> bool:
        return self.money >= VITAMIN_PRICE

    def buy_vitamin(self, mon_index: int, stat: str) -> bool:
        if not self.can_afford_vitamin():
            return False
        if mon_index < 0 or mon_index >= len(self.pokemon):
            return False
        mon = self.pokemon[mon_index]
        if mon.use_vitamin(stat):
            self.money -= VITAMIN_PRICE
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "pokemon": [p.to_dict() for p in self.pokemon],
            "money": self.money,
            "exp_share_holder": self.exp_share_holder,
            "amulet_coin_holder": self.amulet_coin_holder,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Party":
        party = cls(
            money=d.get("money", 0),
            exp_share_holder=d.get("exp_share_holder"),
            amulet_coin_holder=d.get("amulet_coin_holder", False),
        )
        for pd in d.get("pokemon", []):
            party.pokemon.append(Pokemon.from_dict(pd))
        return party


@dataclass
class WildSpot:
    location: str
    location_id: str
    method: str
    pokemon_evs: dict[str, dict[str, int]]
    encounter_rates: dict[str, float]
    levels: dict[str, tuple[int, int]]
    version: str = "both"

    def ev_rate(self, stat: str) -> float:
        stat = normalize_stat(stat)
        total = 0.0
        for species, rate in self.encounter_rates.items():
            evs = self.pokemon_evs.get(species, {})
            total += (rate / 100.0) * evs.get(stat, 0)
        return total

    def purity(self, stat: str) -> float:
        stat = normalize_stat(stat)
        target_rate = 0.0
        other_rate = 0.0
        for species, rate in self.encounter_rates.items():
            evs = self.pokemon_evs.get(species, {})
            if evs.get(stat, 0) > 0:
                target_rate += rate
            elif any(evs.get(s, 0) > 0 for s in STATS if s != stat):
                other_rate += rate
        total = target_rate + other_rate
        if total == 0:
            return 0.0
        return 100.0 * target_rate / total

    def avg_level(self) -> float:
        total_rate = sum(self.encounter_rates.values())
        if total_rate == 0:
            return 0
        weighted = 0.0
        for species, rate in self.encounter_rates.items():
            lo, hi = self.levels.get(species, (1, 1))
            avg = (lo + hi) / 2.0
            weighted += rate * avg
        return weighted / total_rate


@dataclass
class TrainerSpot:
    location: str
    trainer_name: str
    trainer_class: str
    pokemon_list: list[dict]
    vs_seeker: bool = True
    version: str = "both"

    def total_evs(self, stat: str) -> int:
        stat = normalize_stat(stat)
        return sum(p.get("evs", {}).get(stat, 0) for p in self.pokemon_list)

    def last_mon_level(self) -> int:
        if not self.pokemon_list:
            return 1
        return self.pokemon_list[-1].get("level", 1)

    def money_reward(self, amulet_coin: bool = False) -> int:
        multiplier = TRAINER_MONEY_TABLE.get(self.trainer_class.upper(), 4)
        base = 4 * self.last_mon_level() * multiplier
        if amulet_coin:
            base *= 2
        return base

    def purity(self, stat: str) -> float:
        stat = normalize_stat(stat)
        target = 0
        total = 0
        for p in self.pokemon_list:
            evs = p.get("evs", {})
            ev_stat = evs.get(stat, 0)
            ev_total = sum(evs.get(s, 0) for s in STATS)
            if ev_stat > 0:
                target += ev_stat
            total += ev_total
        if total == 0:
            return 0.0
        return 100.0 * target / total


def battles_to_goal(remaining: int, ev_per_battle: float, macho_brace: bool = False) -> int:
    if ev_per_battle <= 0:
        return 999999
    multiplier = 2 if macho_brace else 1
    effective = ev_per_battle * multiplier
    return math.ceil(remaining / effective)


def vitamin_strategy(
    current_ev: int,
    target_ev: int,
    current_money: int,
    battles_planned: int,
    money_per_battle: int,
) -> dict:
    remaining = target_ev - current_ev
    if remaining <= 0:
        return {"vitamins": 0, "cost": 0, "evs_from_vitamins": 0, "remaining_after": 0}

    vitamins_room = max(0, (VITAMIN_CAP - current_ev) // VITAMIN_EV)
    projected_money = current_money + (battles_planned * money_per_battle)
    vitamins_affordable = projected_money // VITAMIN_PRICE
    vitamins_needed = min(remaining // VITAMIN_EV, vitamins_room)
    vitamins_to_use = min(vitamins_affordable, vitamins_needed, vitamins_room)

    return {
        "vitamins": vitamins_to_use,
        "cost": vitamins_to_use * VITAMIN_PRICE,
        "evs_from_vitamins": vitamins_to_use * VITAMIN_EV,
        "remaining_after": remaining - (vitamins_to_use * VITAMIN_EV),
    }


def rank_wild_spots(spots: list[WildSpot], stat: str) -> list[tuple[WildSpot, float]]:
    stat = normalize_stat(stat)
    scored = []
    for spot in spots:
        ev_rate = spot.ev_rate(stat)
        purity = spot.purity(stat)
        if ev_rate > 0:
            score = ev_rate * (purity / 100.0)
            scored.append((spot, score))
    return sorted(scored, key=lambda x: -x[1])


def rank_trainer_spots(spots: list[TrainerSpot], stat: str, amulet_coin: bool = False) -> list[tuple[TrainerSpot, float]]:
    stat = normalize_stat(stat)
    scored = []
    for spot in spots:
        total_evs = spot.total_evs(stat)
        if total_evs > 0:
            money = spot.money_reward(amulet_coin)
            score = total_evs + (money / 10000.0)
            scored.append((spot, score))
    return sorted(scored, key=lambda x: -x[1])


def load_ev_data(path: Path | None = None) -> dict:
    path = path or EV_DATA_FILE
    if not path.is_file():
        return {"wild_spots": [], "species_evs": {}}
    return json.loads(_read_utf8(path))


def load_trainer_spots(path: Path | None = None) -> list[TrainerSpot]:
    path = path or TRAINER_SPOTS_FILE
    if not path.is_file():
        return []
    data = json.loads(_read_utf8(path))
    spots = []
    for entry in data.get("trainers", []):
        spots.append(TrainerSpot(
            location=entry.get("location", ""),
            trainer_name=entry.get("trainer_name", ""),
            trainer_class=entry.get("trainer_class", ""),
            pokemon_list=entry.get("pokemon", []),
            vs_seeker=entry.get("vs_seeker", True),
            version=entry.get("version", "both"),
        ))
    return spots


class Session:
    def __init__(self, party: Party | None = None):
        self.party = party or Party()
        self.active_index: int = 0
        self.battle_count: int = 0

    @property
    def active_pokemon(self) -> Pokemon | None:
        if 0 <= self.active_index < len(self.party.pokemon):
            return self.party.pokemon[self.active_index]
        return None

    def record_ko(self, ev_yields: dict[str, int]) -> dict[str, int]:
        gains = {}
        active = self.active_pokemon
        if active:
            multiplier = 2 if active.using_macho_brace else 1
            for stat, base in ev_yields.items():
                stat = normalize_stat(stat)
                actual = active.add_evs(stat, base * multiplier)
                gains[stat] = actual

        if self.party.exp_share_holder is not None:
            holder = self.party.pokemon[self.party.exp_share_holder]
            if holder != active:
                mult = 2 if holder.using_macho_brace else 1
                for stat, base in ev_yields.items():
                    stat = normalize_stat(stat)
                    holder.add_evs(stat, base * mult)

        self.battle_count += 1
        return gains

    def to_dict(self) -> dict:
        return {
            "party": self.party.to_dict(),
            "active_index": self.active_index,
            "battle_count": self.battle_count,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        session = cls()
        session.party = Party.from_dict(d.get("party", {}))
        session.active_index = d.get("active_index", 0)
        session.battle_count = d.get("battle_count", 0)
        return session


def save_session(session: Session, path: Path) -> None:
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding=JSON_ENCODING)


def load_session(path: Path) -> Session | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(_read_utf8(path))
        return Session.from_dict(data)
    except (json.JSONDecodeError, KeyError):
        return None


COMMON_SPREADS = [
    ("Physical Sweeper", {"Attack": 252, "Speed": 252, "HP": 4}),
    ("Special Sweeper", {"SpAtk": 252, "Speed": 252, "HP": 4}),
    ("Physical Tank", {"HP": 252, "Attack": 252, "Defense": 4}),
    ("Special Tank", {"HP": 252, "SpAtk": 252, "SpDef": 4}),
    ("Physical Wall", {"HP": 252, "Defense": 252, "SpDef": 4}),
    ("Special Wall", {"HP": 252, "SpDef": 252, "Defense": 4}),
    ("Mixed Wall", {"HP": 252, "Defense": 128, "SpDef": 128}),
    ("Fast Physical", {"Attack": 252, "Speed": 252, "Defense": 4}),
    ("Bulky Attacker", {"HP": 128, "Attack": 252, "Speed": 128}),
]


def validate_ev_spread(spread: dict[str, int]) -> list[str]:
    errors = []
    total = sum(spread.values())
    if total > MAX_TOTAL_EVS:
        errors.append(f"Total EVs ({total}) exceed maximum ({MAX_TOTAL_EVS})")
    for stat, val in spread.items():
        if val > MAX_PER_STAT_EVS:
            errors.append(f"{stat} EVs ({val}) exceed maximum ({MAX_PER_STAT_EVS})")
        if val < 0:
            errors.append(f"{stat} EVs cannot be negative")
    return errors


def format_ev_summary(mon: Pokemon) -> str:
    lines = [f"{mon.name}:"]
    for stat in STATS:
        current = mon.current_evs.get(stat, 0)
        target = mon.target_evs.get(stat, 0)
        if target > 0:
            remaining = max(0, target - current)
            lines.append(f"  {stat}: {current}/{target} ({remaining} left)")
    total_cur = mon.total_current()
    total_tar = mon.total_target()
    lines.append(f"  Total: {total_cur}/{total_tar}")
    if mon.using_macho_brace:
        lines.append("  [Macho Brace: 2x EVs]")
    return "\n".join(lines)


if __name__ == "__main__":
    print("EV Trainer - Core Module")
    print("Run ev_trainer_gui.py for the Pythonista interface.")
    print()
    print("Quick test:")
    mon = Pokemon("Alakazam", {"SpAtk": 252, "Speed": 252, "HP": 4})
    print(format_ev_summary(mon))
    print()
    print(f"Battles for 252 SpAtk @ 1 EV/battle: {battles_to_goal(252, 1.0)}")
    print(f"Battles for 252 SpAtk @ 1 EV/battle + Macho Brace: {battles_to_goal(252, 1.0, True)}")
