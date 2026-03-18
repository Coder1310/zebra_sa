from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


ROLES_6 = ["Russian", "English", "Chinese", "German", "French", "American"]
HOUSE_COLORS_6 = ["Red", "Blue", "Yellow", "Green", "White", "Black"]
DRINKS_6 = ["Water", "Beer", "Juice", "Whiskey", "Vodka", "Wine"]
SMOKES_6 = ["Marlboro", "PallMall", "Dunhill", "Kent", "Camel", "Parlament"]
PETS_6 = ["Dog", "Cat", "Zebra", "Fish", "Hamster", "Bear"]

KNOWLEDGE_CATEGORIES = ("color", "nationality", "pet", "drink", "smoke")
M1_CATEGORIES = ("nationality", "pet", "drink", "smoke")


@dataclass(frozen = True)
class House:
  house_id: int
  color: str


DEFAULT_STRATEGIES_6: dict[str, dict[str, Any]] = {
  "Russian": {"p_to": [100, 0, 0, 0, 0, 0], "p_house_exch": 70, "p_pet_exch": 70},
  "English": {"p_to": [30, 10, 10, 25, 25, 0], "p_house_exch": 50, "p_pet_exch": 50},
  "Chinese": {"p_to": [30, 20, 20, 20, 20, 0], "p_house_exch": 50, "p_pet_exch": 50},
  "German": {"p_to": [50, 0, 0, 0, 0, 50], "p_house_exch": 25, "p_pet_exch": 25},
  "French": {"p_to": [10, 10, 0, 10, 20, 50], "p_house_exch": 90, "p_pet_exch": 40},
  "American": {"p_to": [15, 15, 15, 15, 20, 20], "p_house_exch": 100, "p_pet_exch": 100},
}

FULL_GRAPH_6 = {
  (1, 1): 7, (1, 2): 10, (1, 3): 2, (1, 4): 4, (1, 5): 5, (1, 6): 3,
  (2, 1): 7, (2, 2): 4, (2, 3): 5, (2, 4): 8, (2, 5): 7, (2, 6): 9,
  (3, 1): 8, (3, 2): 7, (3, 3): 1, (3, 4): 8, (3, 5): 1, (3, 6): 3,
  (4, 1): 3, (4, 2): 4, (4, 3): 6, (4, 4): 2, (4, 5): 6, (4, 6): 8,
  (5, 1): 7, (5, 2): 10, (5, 3): 7, (5, 4): 4, (5, 5): 1, (5, 6): 8,
  (6, 1): 8, (6, 2): 2, (6, 3): 4, (6, 4): 10, (6, 5): 5, (6, 6): 7,
}


def clamp_int(x: Any, lo: int, hi: int) -> int:
  try:
    value = int(x)
  except Exception:
    return lo
  if value < lo:
    return lo
  if value > hi:
    return hi
  return value


def normalize_probs(values: list[int]) -> list[int]:
  clean = [max(0, int(x)) for x in values]
  total = sum(clean)
  if total <= 0:
    if not clean:
      return []
    base = 100 // len(clean)
    result = [base] * len(clean)
    result[-1] += 100 - sum(result)
    return result

  result: list[int] = []
  acc = 0
  for value in clean:
    normalized = int(round(100.0 * value / total))
    result.append(normalized)
    acc += normalized
  if result and acc != 100:
    result[-1] += 100 - acc
  return result


def pick_by_probs(rng: random.Random, items: list[int], probs: list[int]) -> int:
  normalized = normalize_probs(probs)
  threshold = rng.randint(1, 100)
  prefix = 0
  for item, prob in zip(items, normalized):
    prefix += prob
    if threshold <= prefix:
      return item
  return items[-1]


def roles_for(agents: int, houses: int) -> list[str]:
  if agents == 6 and houses == 6:
    return list(ROLES_6)
  return [f"a{i}" for i in range(agents)]


def houses_for(houses: int) -> list[House]:
  if houses == 6:
    return [House(i + 1, HOUSE_COLORS_6[i]) for i in range(6)]
  return [House(i + 1, f"Color{i + 1}") for i in range(houses)]


def ring_distances(houses: int) -> dict[tuple[int, int], int]:
  dist: dict[tuple[int, int], int] = {}
  for house in range(1, houses + 1):
    left = house - 1 if house > 1 else houses
    right = house + 1 if house < houses else 1
    dist[(house, house)] = 0
    dist[(house, left)] = 1
    dist[(house, right)] = 1
  return dist


def distances_for(graph: str, houses: int) -> dict[tuple[int, int], int]:
  if graph == "full" and houses == 6:
    return dict(FULL_GRAPH_6)
  return ring_distances(houses)


def default_strategies_for(houses: int) -> dict[str, dict[str, Any]]:
  if houses == 6:
    return {name: dict(value) for name, value in DEFAULT_STRATEGIES_6.items()}
  return {}