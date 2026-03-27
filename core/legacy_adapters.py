from __future__ import annotations

from typing import Any

from core.schema import BeliefSnapshot, TruthSnapshot


def _entry_value(entry: Any) -> str:
  if hasattr(entry, "value"):
    return str(entry.value)
  return str(entry)


def truth_from_legacy_world(houses: list[Any], agents: list[Any]) -> TruthSnapshot:
  house_color: dict[int, str] = {}
  person_home: dict[str, int] = {}
  person_pet: dict[str, str] = {}
  person_drink: dict[str, str] = {}
  person_smoke: dict[str, str] = {}
  person_location: dict[str, int] = {}

  for house in houses:
    house_color[int(house.house_id)] = str(house.color)

  for agent in agents:
    name = str(agent.name)
    person_home[name] = int(agent.home)
    person_pet[name] = str(agent.pet)
    person_drink[name] = str(agent.drink)
    person_smoke[name] = str(agent.smoke)
    person_location[name] = int(agent.location)

  return TruthSnapshot(
    house_color = house_color,
    person_home = person_home,
    person_pet = person_pet,
    person_drink = person_drink,
    person_smoke = person_smoke,
    person_location = person_location,
  )


def belief_from_legacy_agent(knowledge: dict[tuple[int, str], Any]) -> BeliefSnapshot:
  belief = BeliefSnapshot()
  by_house: dict[int, dict[str, str]] = {}

  for key, raw_entry in knowledge.items():
    house_id, category = key
    value = _entry_value(raw_entry)

    row = by_house.setdefault(int(house_id), {})
    row[str(category)] = value

    if category == "color":
      belief.house_color[int(house_id)] = value

    if category == "nationality":
      belief.house_resident[int(house_id)] = value
      belief.person_home[value] = int(house_id)

  for house_id, row in by_house.items():
    person = row.get("nationality")
    if not person:
      continue

    if "pet" in row:
      belief.person_pet[person] = row["pet"]

    if "drink" in row:
      belief.person_drink[person] = row["drink"]

    if "smoke" in row:
      belief.person_smoke[person] = row["smoke"]

  return belief