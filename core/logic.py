from __future__ import annotations

import random
import xml.etree.ElementTree as ET
from typing import Any

from core.schema import Agent, AgentMetrics, BeliefSnapshot, KnowledgeEntry, TruthSnapshot


def _k(kind: str, entity: str | int) -> tuple[str, str]:
  return kind, str(entity)


def write_xml_log(path: Any, session_id: str, events: list[dict[str, Any]]) -> None:
  root = ET.Element("log", session=session_id)
  events_node = ET.SubElement(root, "events")

  for event in events:
    event_node = ET.SubElement(
      events_node,
      "event",
      id=str(event["id"]),
      day=str(event["day"]),
      type=str(event["type"]),
    )
    for index, arg in enumerate(event.get("args", []), start=1):
      arg_node = ET.SubElement(event_node, "arg", i=str(index))
      arg_node.text = "" if arg is None else str(arg)

  ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=False)


def observe_house(agent: Agent, day: int, house_id: int, houses: list[Any], resident: Agent | None) -> None:
  agent.knowledge[_k("house_color", house_id)] = KnowledgeEntry(str(houses[house_id - 1].color), day)
  if resident is None:
    return

  agent.knowledge[_k("person_home", resident.name)] = KnowledgeEntry(str(house_id), day)
  agent.knowledge[_k("person_pet", resident.name)] = KnowledgeEntry(str(resident.pet), day)
  agent.knowledge[_k("person_drink", resident.name)] = KnowledgeEntry(str(resident.drink), day)
  agent.knowledge[_k("person_smoke", resident.name)] = KnowledgeEntry(str(resident.smoke), day)


def observe_person(agent: Agent, day: int, other: Agent) -> None:
  agent.knowledge[_k("person_home", other.name)] = KnowledgeEntry(str(other.home), day)
  agent.knowledge[_k("person_pet", other.name)] = KnowledgeEntry(str(other.pet), day)
  agent.knowledge[_k("person_drink", other.name)] = KnowledgeEntry(str(other.drink), day)
  agent.knowledge[_k("person_smoke", other.name)] = KnowledgeEntry(str(other.smoke), day)


def merge_knowledge_group(group: list[Agent]) -> None:
  merged: dict[tuple[str, str], KnowledgeEntry] = {}
  for agent in group:
    for key, entry in agent.knowledge.items():
      current = merged.get(key)
      if current is None or entry.day > current.day:
        merged[key] = entry

  for agent in group:
    agent.knowledge = dict(merged)


def random_forget(agent: Agent, rng: random.Random) -> None:
  if not agent.knowledge:
    return
  key = rng.choice(list(agent.knowledge.keys()))
  agent.knowledge.pop(key, None)


def build_truth_snapshot(houses: list[Any], agents: list[Agent]) -> TruthSnapshot:
  house_color = {int(house.house_id): str(house.color) for house in houses}
  person_home = {agent.name: int(agent.home) for agent in agents}
  person_pet = {agent.name: str(agent.pet) for agent in agents}
  person_drink = {agent.name: str(agent.drink) for agent in agents}
  person_smoke = {agent.name: str(agent.smoke) for agent in agents}
  person_location = {agent.name: int(agent.location) for agent in agents}

  return TruthSnapshot(
    house_color=house_color,
    person_home=person_home,
    person_pet=person_pet,
    person_drink=person_drink,
    person_smoke=person_smoke,
    person_location=person_location,
  )


def build_belief_snapshot(knowledge: dict[tuple[str, str], KnowledgeEntry]) -> BeliefSnapshot:
  belief = BeliefSnapshot()

  for (kind, entity), entry in knowledge.items():
    if kind == "house_color":
      belief.house_color[int(entity)] = str(entry.value)
      continue

    if kind == "person_home":
      try:
        home = int(entry.value)
      except Exception:
        continue
      belief.person_home[entity] = home
      belief.house_resident[home] = entity
      continue

    if kind == "person_pet":
      belief.person_pet[entity] = str(entry.value)
      continue

    if kind == "person_drink":
      belief.person_drink[entity] = str(entry.value)
      continue

    if kind == "person_smoke":
      belief.person_smoke[entity] = str(entry.value)

  return belief


def _true_zebra_owner(truth: TruthSnapshot) -> str | None:
  for person, pet in truth.person_pet.items():
    if pet == "Zebra":
      return person
  return None


def _predicted_zebra_owner(belief: BeliefSnapshot) -> str | None:
  owners = [person for person, pet in belief.person_pet.items() if pet == "Zebra"]
  if len(owners) == 1:
    return owners[0]

  if belief.zebra_owner_probs:
    return max(belief.zebra_owner_probs.items(), key=lambda item: float(item[1]))[0]

  return None


def evaluate_agent_metrics(truth: TruthSnapshot, belief: BeliefSnapshot) -> AgentMetrics:
  persons = sorted(truth.person_home.keys())
  known = 0
  correct = 0
  total = len(persons) * 4

  for person in persons:
    if person in belief.person_home:
      known += 1
      if belief.person_home[person] == truth.person_home[person]:
        correct += 1

    if person in belief.person_pet:
      known += 1
      if belief.person_pet[person] == truth.person_pet[person]:
        correct += 1

    if person in belief.person_drink:
      known += 1
      if belief.person_drink[person] == truth.person_drink[person]:
        correct += 1

    if person in belief.person_smoke:
      known += 1
      if belief.person_smoke[person] == truth.person_smoke[person]:
        correct += 1

  zebra_owner_true = _true_zebra_owner(truth)
  zebra_owner_pred = _predicted_zebra_owner(belief)
  zebra_resolved = zebra_owner_pred is not None
  m2_zebra = int(zebra_owner_true is not None and zebra_owner_pred == zebra_owner_true)

  return AgentMetrics(
    known_personal_facts=known,
    correct_personal_facts=correct,
    total_personal_facts=total,
    m1_personal=(correct / total) if total else 0.0,
    zebra_owner_true=zebra_owner_true,
    zebra_owner_pred=zebra_owner_pred,
    zebra_resolved=zebra_resolved,
    m2_zebra=m2_zebra,
  )


def m1_from_belief(truth: TruthSnapshot, belief: BeliefSnapshot) -> float:
  return evaluate_agent_metrics(truth, belief).m1_personal


def knowledge_rows(houses_n: int, belief: BeliefSnapshot) -> list[dict[str, Any]]:
  rows: list[dict[str, Any]] = []

  for house_id in range(1, houses_n + 1):
    resident = belief.house_resident.get(house_id)
    row: dict[str, Any] = {
      "house": house_id,
      "color": belief.house_color.get(house_id),
      "nationality": resident,
      "pet": None,
      "drink": None,
      "smoke": None,
    }
    if resident:
      row["pet"] = belief.person_pet.get(resident)
      row["drink"] = belief.person_drink.get(resident)
      row["smoke"] = belief.person_smoke.get(resident)
    rows.append(row)

  return rows